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