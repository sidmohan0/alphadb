-- BTC Features Continuous Aggregate

\echo 'Creating BTC features continuous aggregate...'

CREATE MATERIALIZED VIEW features_btc_1m
WITH (timescaledb.continuous)
AS
SELECT
    time_bucket('1 minute', ts) AS bucket,
    
    -- OHLCV data  
    FIRST(open, ts) AS open_price,
    MAX(high) AS high_price,
    MIN(low) AS low_price,
    LAST(close, ts) AS close_price,
    SUM(vol) AS volume,
    
    -- Basic derived features computed in aggregation
    MAX(high) - MIN(low) AS hl_range,
    (MAX(high) - MIN(low)) / NULLIF(LAST(close, ts), 0) AS hl_range_pct,
    ABS(LAST(close, ts) - FIRST(open, ts)) AS body_size,
    ABS(LAST(close, ts) - FIRST(open, ts)) / NULLIF(LAST(close, ts), 0) AS body_pct,
    
    -- VWAP gap (approximated with OHLC4)
    LAST(close, ts) - ((FIRST(open, ts) + MAX(high) + MIN(low) + LAST(close, ts)) / 4.0) AS vwap_gap,
    
    -- Parkinson volatility estimator
    CASE 
        WHEN MAX(high) > 0 AND MIN(low) > 0 AND MAX(high) >= MIN(low)
        THEN 0.5 * POWER(LN(MAX(high) / MIN(low)), 2)
        ELSE NULL
    END AS parkinson_vol,
    
    -- Price position within the bar
    CASE 
        WHEN MAX(high) > MIN(low) 
        THEN (LAST(close, ts) - MIN(low)) / (MAX(high) - MIN(low))
        ELSE 0.5
    END AS price_position,
    
    -- Candle type indicators
    CASE WHEN LAST(close, ts) > FIRST(open, ts) THEN 1 ELSE 0 END AS is_green,
    CASE WHEN ABS(LAST(close, ts) - FIRST(open, ts)) / NULLIF(LAST(close, ts), 0) < 0.001 THEN 1 ELSE 0 END AS is_doji
    
FROM ohlcv_btc_usdt
GROUP BY bucket;