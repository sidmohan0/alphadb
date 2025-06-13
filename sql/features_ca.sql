-- Feature Engineering Continuous Aggregate for AlphaDB
-- Creates real-time feature computation with 1-minute refresh
-- Computes: log-returns, volume z-score, VWAP gap, Parkinson volatility

------------------  Check preconditions  ------------------
\echo 'Checking TimescaleDB extension...'
\dx

\echo 'Checking base hypertables...'
\d ohlcv_btc_usdt
\d ohlcv_eth_usdt

------------------  Create features_1m continuous aggregate  ------------------
\echo 'Creating features_1m continuous aggregate...'

CREATE MATERIALIZED VIEW IF NOT EXISTS features_1m
WITH (timescaledb.continuous)
AS
SELECT
    bucket,
    symbol,
    last_close,
    
    -- Log return (minute-over-minute)
    CASE 
        WHEN LAG(last_close) OVER (PARTITION BY symbol ORDER BY bucket) IS NOT NULL 
             AND LAG(last_close) OVER (PARTITION BY symbol ORDER BY bucket) > 0
        THEN LN(last_close / LAG(last_close) OVER (PARTITION BY symbol ORDER BY bucket))
        ELSE NULL
    END AS log_return,
    
    vol,
    
    -- Volume moving averages and z-score (1440 minutes = 1 day)
    AVG(vol) OVER (
        PARTITION BY symbol 
        ORDER BY bucket 
        ROWS BETWEEN 1439 PRECEDING AND CURRENT ROW
    ) AS ma_vol_1d,
    
    STDDEV_POP(vol) OVER (
        PARTITION BY symbol 
        ORDER BY bucket 
        ROWS BETWEEN 1439 PRECEDING AND CURRENT ROW
    ) AS std_vol_1d,
    
    -- Volume z-score
    CASE 
        WHEN STDDEV_POP(vol) OVER (
            PARTITION BY symbol 
            ORDER BY bucket 
            ROWS BETWEEN 1439 PRECEDING AND CURRENT ROW
        ) > 0
        THEN (vol - AVG(vol) OVER (
            PARTITION BY symbol 
            ORDER BY bucket 
            ROWS BETWEEN 1439 PRECEDING AND CURRENT ROW
        )) / STDDEV_POP(vol) OVER (
            PARTITION BY symbol 
            ORDER BY bucket 
            ROWS BETWEEN 1439 PRECEDING AND CURRENT ROW
        )
        ELSE NULL
    END AS volume_z,
    
    -- VWAP gap (approximated with OHLC4)
    last_close - ((open + high + low + close) / 4.0) AS vwap_gap,
    
    -- Parkinson volatility estimator
    CASE 
        WHEN high > 0 AND low > 0 AND high >= low
        THEN 0.5 * POWER(LN(high / low), 2)
        ELSE NULL
    END AS parkinson_vol,
    
    -- Additional useful features
    high - low AS hl_range,
    (high - low) / NULLIF(last_close, 0) AS hl_range_pct,
    ABS(close - open) / NULLIF(last_close, 0) AS body_pct
    
FROM (
    -- Unified view combining BTC and ETH data
    SELECT
        time_bucket('1 minute', ts) AS bucket,
        'BTC/USDT' AS symbol,
        FIRST(open, ts) AS open,
        MAX(high) AS high,
        MIN(low) AS low,
        LAST(close, ts) AS close,
        SUM(vol) AS vol,
        LAST(close, ts) AS last_close
    FROM ohlcv_btc_usdt
    GROUP BY bucket
    
    UNION ALL
    
    SELECT
        time_bucket('1 minute', ts) AS bucket,
        'ETH/USDT' AS symbol,
        FIRST(open, ts) AS open,
        MAX(high) AS high,
        MIN(low) AS low,
        LAST(close, ts) AS close,
        SUM(vol) AS vol,
        LAST(close, ts) AS last_close
    FROM ohlcv_eth_usdt
    GROUP BY bucket
) AS combined_bars
ORDER BY symbol, bucket;