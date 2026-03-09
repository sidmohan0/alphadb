CREATE TABLE IF NOT EXISTS market_state_schema_migrations (
  schema_name TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS market_user_states (
  user_id TEXT PRIMARY KEY,
  saved_markets JSONB NOT NULL DEFAULT '[]'::jsonb,
  recent_markets JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_user_states_updated_at
  ON market_user_states (updated_at DESC);
