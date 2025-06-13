-- Continuous Aggregate Refresh Policies for Features

\echo 'Setting up refresh policies for feature continuous aggregates...'

-- BTC features refresh policy (every 1 minute)
SELECT add_continuous_aggregate_policy(
  'features_btc_1m',
  start_offset      => INTERVAL '1 hour',      -- backfill safety net
  end_offset        => INTERVAL '1 minute',    -- keep 1 minute behind realtime
  schedule_interval => INTERVAL '1 minute'     -- job frequency
);

-- ETH features refresh policy (every 1 minute)
SELECT add_continuous_aggregate_policy(
  'features_eth_1m',
  start_offset      => INTERVAL '1 hour',      -- backfill safety net
  end_offset        => INTERVAL '1 minute',    -- keep 1 minute behind realtime
  schedule_interval => INTERVAL '1 minute'     -- job frequency
);

\echo 'Refresh policies created successfully!'
\echo 'Features will now auto-refresh every minute.'