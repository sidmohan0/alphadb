from alphadb.config import settings_from_env


def test_settings_default_database_url_uses_configurable_local_port() -> None:
    settings = settings_from_env({})

    assert settings.database_url == "postgresql://alphadb:alphadb@localhost:55433/alphadb"
    assert settings.streamlit_port == "8501"
    assert settings.kalshi_base_url == "https://external-api.kalshi.com/trade-api/v2"


def test_settings_database_url_can_be_overridden() -> None:
    settings = settings_from_env(
        {
            "DATABASE_URL": "postgresql://user:pass@postgres:5432/custom",
            "ALPHADB_ENV": "test",
            "ALPHADB_STREAMLIT_PORT": "18501",
            "ALPHADB_KALSHI_BASE_URL": "https://example.test/trade-api/v2",
        }
    )

    assert settings.database_url == "postgresql://user:pass@postgres:5432/custom"
    assert settings.environment == "test"
    assert settings.streamlit_port == "18501"
    assert settings.kalshi_base_url == "https://example.test/trade-api/v2"
