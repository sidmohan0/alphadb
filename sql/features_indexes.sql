-- Performance Indexes for Feature Continuous Aggregates

\echo 'Creating performance indexes for feature tables...'

-- BTC features indexes
CREATE INDEX IF NOT EXISTS features_btc_1m_bucket_idx
  ON features_btc_1m (bucket DESC);

CREATE INDEX IF NOT EXISTS features_btc_1m_bucket_asc_idx
  ON features_btc_1m (bucket ASC);

-- ETH features indexes  
CREATE INDEX IF NOT EXISTS features_eth_1m_bucket_idx
  ON features_eth_1m (bucket DESC);

CREATE INDEX IF NOT EXISTS features_eth_1m_bucket_asc_idx
  ON features_eth_1m (bucket ASC);

-- Composite indexes for time range queries
CREATE INDEX IF NOT EXISTS features_btc_1m_bucket_close_idx
  ON features_btc_1m (bucket DESC, close_price);

CREATE INDEX IF NOT EXISTS features_eth_1m_bucket_close_idx
  ON features_eth_1m (bucket DESC, close_price);

\echo 'Performance indexes created successfully!'