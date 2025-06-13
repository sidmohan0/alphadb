CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS ohlcv_1m (
  ts   TIMESTAMPTZ PRIMARY KEY,
  open  DOUBLE PRECISION,
  high  DOUBLE PRECISION,
  low   DOUBLE PRECISION,
  close DOUBLE PRECISION,
  vol   DOUBLE PRECISION
);

SELECT create_hypertable('ohlcv_1m', 'ts', chunk_time_interval => INTERVAL '1 day', if_not_exists=>true);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_5m
WITH (timescaledb.continuous)
AS
SELECT
  time_bucket('5 minutes', ts) AS bucket,
  first(open, ts)              AS open,
  max(high)                    AS high,
  min(low)                     AS low,
  last(close, ts)              AS close,
  sum(vol)                     AS vol
FROM ohlcv_1m
GROUP BY bucket;

-- Trades table for tick-level data
CREATE TABLE IF NOT EXISTS trades (
  ts_exchange   TIMESTAMPTZ NOT NULL,
  ts_ingest     TIMESTAMPTZ NOT NULL DEFAULT now(),
  venue         TEXT        NOT NULL,
  symbol        TEXT        NOT NULL,
  side          TEXT        NOT NULL CHECK (side IN ('buy','sell')),
  price         DOUBLE PRECISION NOT NULL,
  qty           DOUBLE PRECISION NOT NULL,
  PRIMARY KEY   (ts_exchange, venue, symbol, side)
);

SELECT create_hypertable('trades','ts_exchange', if_not_exists=>true);
CREATE INDEX IF NOT EXISTS trades_symbol_time ON trades (symbol, ts_exchange DESC);

-- Symbol-specific OHLCV tables for REST API data
-- BTC/USDT minute bars
CREATE TABLE IF NOT EXISTS ohlcv_btc_usdt (
  ts   TIMESTAMPTZ PRIMARY KEY,
  open  DOUBLE PRECISION,
  high  DOUBLE PRECISION,
  low   DOUBLE PRECISION,
  close DOUBLE PRECISION,
  vol   DOUBLE PRECISION
);

SELECT create_hypertable('ohlcv_btc_usdt', 'ts', chunk_time_interval => INTERVAL '1 day', if_not_exists=>true);

-- ETH/USDT minute bars  
CREATE TABLE IF NOT EXISTS ohlcv_eth_usdt (
  ts   TIMESTAMPTZ PRIMARY KEY,
  open  DOUBLE PRECISION,
  high  DOUBLE PRECISION,
  low   DOUBLE PRECISION,
  close DOUBLE PRECISION,
  vol   DOUBLE PRECISION
);

SELECT create_hypertable('ohlcv_eth_usdt', 'ts', chunk_time_interval => INTERVAL '1 day', if_not_exists=>true);

-- Create 5-minute continuous aggregates for each symbol
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_btc_usdt_5m
WITH (timescaledb.continuous)
AS
SELECT
  time_bucket('5 minutes', ts) AS bucket,
  first(open, ts)              AS open,
  max(high)                    AS high,
  min(low)                     AS low,
  last(close, ts)              AS close,
  sum(vol)                     AS vol
FROM ohlcv_btc_usdt
GROUP BY bucket;

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_eth_usdt_5m
WITH (timescaledb.continuous)
AS
SELECT
  time_bucket('5 minutes', ts) AS bucket,
  first(open, ts)              AS open,
  max(high)                    AS high,
  min(low)                     AS low,
  last(close, ts)              AS close,
  sum(vol)                     AS vol
FROM ohlcv_eth_usdt
GROUP BY bucket;