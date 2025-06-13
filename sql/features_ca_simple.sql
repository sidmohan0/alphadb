-- Simple Feature Engineering Continuous Aggregate for AlphaDB
-- Creates basic features without complex window functions

\echo 'Creating simple features_1m continuous aggregate...'

-- Drop existing view if it exists
DROP MATERIALIZED VIEW IF EXISTS features_1m;

-- Create basic continuous aggregate
CREATE MATERIALIZED VIEW features_1m
WITH (timescaledb.continuous)
AS
SELECT
    bucket,
    symbol,
    open,
    high,
    low,
    close,
    vol,
    
    -- Basic features without window functions
    high - low AS hl_range,
    (high - low) / NULLIF(close, 0) AS hl_range_pct,
    ABS(close - open) AS body_size,
    ABS(close - open) / NULLIF(close, 0) AS body_pct,
    
    -- VWAP gap (approximated with OHLC4)
    close - ((open + high + low + close) / 4.0) AS vwap_gap,
    
    -- Parkinson volatility estimator
    CASE 
        WHEN high > 0 AND low > 0 AND high >= low
        THEN 0.5 * POWER(LN(high / low), 2)
        ELSE NULL
    END AS parkinson_vol,
    
    -- Volume metrics
    vol AS volume,
    
    -- Price position within the bar
    CASE 
        WHEN high > low 
        THEN (close - low) / (high - low)
        ELSE 0.5
    END AS price_position
    
FROM (
    -- Unified view combining BTC and ETH data
    SELECT
        time_bucket('1 minute', ts) AS bucket,
        'BTC/USDT' AS symbol,
        FIRST(open, ts) AS open,
        MAX(high) AS high,
        MIN(low) AS low,
        LAST(close, ts) AS close,
        SUM(vol) AS vol
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
        SUM(vol) AS vol
    FROM ohlcv_eth_usdt
    GROUP BY bucket
) AS combined_bars;