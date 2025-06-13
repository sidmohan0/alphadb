-- ETH Features Continuous Aggregate

\echo 'Creating ETH features continuous aggregate...'

CREATE MATERIALIZED VIEW features_eth_1m
WITH (timescaledb.continuous)
AS
SELECT
    time_bucket('1 minute', ts_exchange) AS bucket,
    
    -- OHLCV data from tick data
    FIRST(price, ts_exchange) AS open_price,
    MAX(price) AS high_price,
    MIN(price) AS low_price,
    LAST(price, ts_exchange) AS close_price,
    SUM(qty) AS volume,
    
    -- Basic derived features computed in aggregation
    MAX(price) - MIN(price) AS hl_range,
    (MAX(price) - MIN(price)) / NULLIF(LAST(price, ts_exchange), 0) AS hl_range_pct,
    ABS(LAST(price, ts_exchange) - FIRST(price, ts_exchange)) AS body_size,
    ABS(LAST(price, ts_exchange) - FIRST(price, ts_exchange)) / NULLIF(LAST(price, ts_exchange), 0) AS body_pct,
    
    -- VWAP gap (close price - true VWAP)
    LAST(price, ts_exchange) - (SUM(price * qty) / NULLIF(SUM(qty), 0)) AS vwap_gap,
    
    -- Parkinson volatility estimator
    CASE 
        WHEN MAX(price) > 0 AND MIN(price) > 0 AND MAX(price) >= MIN(price)
        THEN 0.5 * POWER(LN(MAX(price) / MIN(price)), 2)
        ELSE NULL
    END AS parkinson_vol,
    
    -- Price position within the bar
    CASE 
        WHEN MAX(price) > MIN(price) 
        THEN (LAST(price, ts_exchange) - MIN(price)) / (MAX(price) - MIN(price))
        ELSE 0.5
    END AS price_position,
    
    -- Candle type indicators
    CASE WHEN LAST(price, ts_exchange) > FIRST(price, ts_exchange) THEN 1 ELSE 0 END AS is_green,
    CASE WHEN ABS(LAST(price, ts_exchange) - FIRST(price, ts_exchange)) / NULLIF(LAST(price, ts_exchange), 0) < 0.001 THEN 1 ELSE 0 END AS is_doji
    
FROM trades
WHERE symbol = 'ETH/USDT'
GROUP BY bucket;