-- Polymarket discovery run schemas
-- Run this in Postgres manually during deployment/migration setup.

CREATE TABLE IF NOT EXISTS discovery_schema_migrations (
  schema_name TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS discovery_runs (
  id TEXT PRIMARY KEY,
  dedupe_key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed')),
  clob_api_url TEXT NOT NULL,
  chain_id INTEGER NOT NULL CHECK (chain_id > 0),
  ws_url TEXT,
  ws_connect_timeout_ms INTEGER NOT NULL CHECK (ws_connect_timeout_ms > 0),
  ws_chunk_size INTEGER NOT NULL CHECK (ws_chunk_size > 0),
  market_fetch_timeout_ms INTEGER NOT NULL CHECK (market_fetch_timeout_ms > 0),
  requested_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  market_count INTEGER NOT NULL DEFAULT 0 CHECK (market_count >= 0),
  market_channel_count INTEGER NOT NULL DEFAULT 0 CHECK (market_channel_count >= 0),
  error_code TEXT,
  error_message TEXT,
  error_retryable BOOLEAN,
  error_details JSONB,
  request_id TEXT NOT NULL,
  dedupe_key_normalized TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT discovery_runs_status_chk CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_status_requested_at
  ON discovery_runs (status, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_requested_at_desc
  ON discovery_runs (requested_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_dedupe_status
  ON discovery_runs (dedupe_key, status);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_expires_at
  ON discovery_runs (expires_at);

CREATE INDEX IF NOT EXISTS idx_discovery_runs_status_expires_at
  ON discovery_runs (status, expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS uk_discovery_runs_dedupe_active
  ON discovery_runs (dedupe_key)
  WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS discovery_run_channels (
  id TEXT PRIMARY KEY,
  discovery_run_id TEXT NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL,
  condition_id TEXT,
  question TEXT,
  outcome TEXT,
  market_slug TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT discovery_run_channels_unique_asset UNIQUE (discovery_run_id, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_discovery_run_channels_run_id
  ON discovery_run_channels (discovery_run_id);

CREATE TABLE IF NOT EXISTS discovery_run_ws_scans (
  id TEXT PRIMARY KEY,
  discovery_run_id TEXT NOT NULL UNIQUE REFERENCES discovery_runs(id) ON DELETE CASCADE,
  ws_url TEXT NOT NULL,
  connected BOOLEAN NOT NULL,
  observed_channels TEXT[] NOT NULL DEFAULT '{}',
  message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
  sample_event_count INTEGER NOT NULL DEFAULT 0 CHECK (sample_event_count >= 0),
  errors JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS discovery_run_events (
  id TEXT PRIMARY KEY,
  discovery_run_id TEXT NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_discovery_run_events_run_id_at
  ON discovery_run_events (discovery_run_id, event_at DESC);
