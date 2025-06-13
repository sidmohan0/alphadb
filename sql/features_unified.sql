-- Unified Features View combining BTC and ETH

\echo 'Creating unified features_1m view...'

CREATE OR REPLACE VIEW features_1m AS
SELECT 
    bucket,
    'BTC/USDT' AS symbol,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    hl_range,
    hl_range_pct,
    body_size,
    body_pct,
    vwap_gap,
    parkinson_vol,
    price_position,
    is_green,
    is_doji
FROM features_btc_1m

UNION ALL

SELECT 
    bucket,
    'ETH/USDT' AS symbol,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    hl_range,
    hl_range_pct,
    body_size,
    body_pct,
    vwap_gap,
    parkinson_vol,
    price_position,
    is_green,
    is_doji
FROM features_eth_1m

ORDER BY symbol, bucket;