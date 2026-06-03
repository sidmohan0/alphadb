import pytest

from alphadb.config import SettingsError, settings_from_env


def test_settings_default_database_url_uses_configurable_local_port() -> None:
    settings = settings_from_env({})

    assert settings.database_url == "postgresql://alphadb:alphadb@localhost:55433/alphadb"
    assert settings.aws_region == "us-east-2"
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
    assert settings.x_api_base_url == "https://api.x.com"
    assert settings.x_api_bearer_token is None
    assert settings.x_api_daily_cap_usd is None
    assert settings.x_api_default_output_root == "artifacts"
    assert settings.live_stake_cap_dollars == 1.0
    assert settings.max_daily_loss_dollars == 10.0
    assert settings.min_ev_dollars == 0.0
    assert settings.strategy_poll_seconds == 60
    assert settings.dashboard_pin is None
    assert settings.dashboard_cookie_secret is None
    assert settings.dashboard_cookie_ttl_seconds == 604800
    assert settings.dashboard_cookie_name == "alphadb_dashboard_auth"


def test_settings_database_url_can_be_overridden() -> None:
    settings = settings_from_env(
        {
            "DATABASE_URL": "postgresql://user:pass@postgres:5432/custom",
            "ALPHADB_ENV": "test",
            "AWS_REGION": "us-east-2",
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
            "ALPHADB_X_API_BASE_URL": "https://api.x.test",
            "ALPHADB_X_BEARER_TOKEN": "x-token",
            "ALPHADB_X_API_DAILY_CAP_USD": "2.50",
            "ALPHADB_X_API_DEFAULT_OUTPUT_ROOT": "research/external-signals",
            "ALPHADB_LIVE_STAKE_CAP_DOLLARS": "2.5",
            "ALPHADB_MAX_DAILY_LOSS_DOLLARS": "25",
            "ALPHADB_MIN_EV_DOLLARS": "0.02",
            "ALPHADB_STRATEGY_POLL_SECONDS": "15",
            "ALPHADB_DASHBOARD_PIN": "1234",
            "ALPHADB_DASHBOARD_COOKIE_SECRET": "test-cookie-secret",
            "ALPHADB_DASHBOARD_COOKIE_TTL_SECONDS": "3600",
            "ALPHADB_DASHBOARD_COOKIE_NAME": "alphadb_test_auth",
        }
    )

    assert settings.database_url == "postgresql://user:pass@postgres:5432/custom"
    assert settings.environment == "test"
    assert settings.aws_region == "us-east-2"
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
    assert settings.x_api_base_url == "https://api.x.test"
    assert settings.x_api_bearer_token == "x-token"
    assert settings.x_api_daily_cap_usd == 2.5
    assert settings.x_api_default_output_root == "research/external-signals"
    assert settings.live_stake_cap_dollars == 2.5
    assert settings.max_daily_loss_dollars == 25.0
    assert settings.min_ev_dollars == 0.02
    assert settings.strategy_poll_seconds == 15
    assert settings.dashboard_pin == "1234"
    assert settings.dashboard_cookie_secret == "test-cookie-secret"
    assert settings.dashboard_cookie_ttl_seconds == 3600
    assert settings.dashboard_cookie_name == "alphadb_test_auth"


def test_dashboard_pin_requires_cookie_secret() -> None:
    with pytest.raises(SettingsError, match="DASHBOARD_COOKIE_SECRET"):
        settings_from_env({"ALPHADB_DASHBOARD_PIN": "1234"})


def test_dashboard_pin_must_be_four_digits() -> None:
    with pytest.raises(SettingsError, match="four digits"):
        settings_from_env(
            {
                "ALPHADB_DASHBOARD_PIN": "12345",
                "ALPHADB_DASHBOARD_COOKIE_SECRET": "test-cookie-secret",
            }
        )


def test_dashboard_cookie_ttl_must_be_positive() -> None:
    with pytest.raises(SettingsError, match="TTL"):
        settings_from_env(
            {
                "ALPHADB_DASHBOARD_PIN": "1234",
                "ALPHADB_DASHBOARD_COOKIE_SECRET": "test-cookie-secret",
                "ALPHADB_DASHBOARD_COOKIE_TTL_SECONDS": "0",
            }
        )
