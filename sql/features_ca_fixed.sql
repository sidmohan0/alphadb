-- Fixed Feature Engineering Continuous Aggregate for AlphaDB
-- Creates basic features with proper aggregation structure

\echo 'Creating fixed features_1m continuous aggregate...'

-- Create basic continuous aggregate with proper structure
CREATE MATERIALIZED VIEW features_1m
WITH (timescaledb.continuous)
AS
SELECT
    bucket,
    symbol,
    
    -- OHLCV data
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    
    -- Basic derived features
    high_price - low_price AS hl_range,
    (high_price - low_price) / NULLIF(close_price, 0) AS hl_range_pct,
    ABS(close_price - open_price) AS body_size,
    ABS(close_price - open_price) / NULLIF(close_price, 0) AS body_pct,
    
    -- VWAP gap (approximated with OHLC4)
    close_price - ((open_price + high_price + low_price + close_price) / 4.0) AS vwap_gap,
    
    -- Parkinson volatility estimator
    CASE 
        WHEN high_price > 0 AND low_price > 0 AND high_price >= low_price
        THEN 0.5 * POWER(LN(high_price / low_price), 2)
        ELSE NULL
    END AS parkinson_vol,
    
    -- Price position within the bar
    CASE 
        WHEN high_price > low_price 
        THEN (close_price - low_price) / (high_price - low_price)
        ELSE 0.5
    END AS price_position,
    
    -- Candle type indicators
    CASE WHEN close_price > open_price THEN 1 ELSE 0 END AS is_green,
    CASE WHEN ABS(close_price - open_price) / NULLIF(close_price, 0) < 0.001 THEN 1 ELSE 0 END AS is_doji
    
FROM (
    -- BTC data aggregated by minute
    SELECT
        time_bucket('1 minute', ts) AS bucket,
        'BTC/USDT' AS symbol,
        FIRST(open, ts) AS open_price,
        MAX(high) AS high_price,
        MIN(low) AS low_price,
        LAST(close, ts) AS close_price,
        SUM(vol) AS volume
    FROM ohlcv_btc_usdt
    GROUP BY bucket
    
    UNION ALL
    
    -- ETH data aggregated by minute
    SELECT
        time_bucket('1 minute', ts) AS bucket,
        'ETH/USDT' AS symbol,
        FIRST(open, ts) AS open_price,
        MAX(high) AS high_price,
        MIN(low) AS low_price,
        LAST(close, ts) AS close_price,
        SUM(vol) AS volume
    FROM ohlcv_eth_usdt
    GROUP BY bucket
) AS minute_bars
GROUP BY bucket, symbol, open_price, high_price, low_price, close_price, volume;