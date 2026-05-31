from alphadb.config import settings_from_env


def test_settings_default_database_url_uses_configurable_local_port() -> None:
    settings = settings_from_env({})

    assert settings.database_url == "postgresql://alphadb:alphadb@localhost:55433/alphadb"
    assert settings.streamlit_port == "8501"
    assert settings.runtime_mode == "fixture"
    assert settings.enable_live_orders is False
    assert settings.human_cutover_approved is False
    assert settings.kalshi_base_url == "https://external-api.kalshi.com/trade-api/v2"
    assert settings.kalshi_ws_url is None
    assert settings.kalshi_api_key_id is None
    assert settings.kalshi_private_key_path is None
    assert settings.enable_live_ws_smoke is False
    assert settings.enable_live_order_smoke is False
    assert settings.artifact_root is None
    assert settings.current_mvp_artifact_config is None
    assert settings.coinbase_product_id == "BTC-USD"
    assert settings.coinbase_granularity_seconds == 60
    assert settings.coinbase_lookback_minutes == 60
    assert settings.live_stake_cap_dollars == 1.0
    assert settings.max_daily_loss_dollars == 10.0
    assert settings.min_ev_dollars == 0.0
    assert settings.strategy_poll_seconds == 60


def test_settings_database_url_can_be_overridden() -> None:
    settings = settings_from_env(
        {
            "DATABASE_URL": "postgresql://user:pass@postgres:5432/custom",
            "ALPHADB_ENV": "test",
            "ALPHADB_STREAMLIT_PORT": "18501",
            "ALPHADB_RUNTIME_MODE": "paper",
            "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
            "ALPHADB_KALSHI_BASE_URL": "https://example.test/trade-api/v2",
            "ALPHADB_KALSHI_WS_URL": "wss://example.test/ws",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
            "ALPHADB_ENABLE_LIVE_WS_SMOKE": "1",
            "ALPHADB_ENABLE_LIVE_ORDER_SMOKE": "1",
            "ALPHADB_ARTIFACT_ROOT": "/tmp/artifacts",
            "ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG": "/tmp/artifacts/config.json",
            "ALPHADB_COINBASE_PRODUCT_ID": "ETH-USD",
            "ALPHADB_COINBASE_GRANULARITY_SECONDS": "300",
            "ALPHADB_COINBASE_LOOKBACK_MINUTES": "120",
            "ALPHADB_LIVE_STAKE_CAP_DOLLARS": "2.5",
            "ALPHADB_MAX_DAILY_LOSS_DOLLARS": "25",
            "ALPHADB_MIN_EV_DOLLARS": "0.02",
            "ALPHADB_STRATEGY_POLL_SECONDS": "15",
        }
    )

    assert settings.database_url == "postgresql://user:pass@postgres:5432/custom"
    assert settings.environment == "test"
    assert settings.streamlit_port == "18501"
    assert settings.runtime_mode == "paper"
    assert settings.enable_live_orders is True
    assert settings.human_cutover_approved is True
    assert settings.kalshi_base_url == "https://example.test/trade-api/v2"
    assert settings.kalshi_ws_url == "wss://example.test/ws"
    assert settings.kalshi_api_key_id == "key-id"
    assert settings.kalshi_private_key_path == "/tmp/key.pem"
    assert settings.enable_live_ws_smoke is True
    assert settings.enable_live_order_smoke is True
    assert settings.artifact_root == "/tmp/artifacts"
    assert settings.current_mvp_artifact_config == "/tmp/artifacts/config.json"
    assert settings.coinbase_product_id == "ETH-USD"
    assert settings.coinbase_granularity_seconds == 300
    assert settings.coinbase_lookback_minutes == 120
    assert settings.live_stake_cap_dollars == 2.5
    assert settings.max_daily_loss_dollars == 25.0
    assert settings.min_ev_dollars == 0.02
    assert settings.strategy_poll_seconds == 15
