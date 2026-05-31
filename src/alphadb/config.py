"""Runtime configuration for local AlphaDB services."""

from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping


DEFAULT_DATABASE_NAME = "alphadb"
DEFAULT_DATABASE_USER = "alphadb"
DEFAULT_DATABASE_PASSWORD = "alphadb"
DEFAULT_DATABASE_HOST = "localhost"
DEFAULT_DATABASE_PORT = "55433"
DEFAULT_KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    streamlit_port: str
    runtime_mode: str
    enable_live_orders: bool
    human_cutover_approved: bool
    kalshi_base_url: str
    kalshi_ws_url: str | None
    kalshi_api_key_id: str | None
    kalshi_private_key_path: str | None
    enable_live_ws_smoke: bool
    enable_live_order_smoke: bool
    artifact_root: str | None
    current_mvp_artifact_config: str | None
    coinbase_product_id: str
    coinbase_granularity_seconds: int
    coinbase_lookback_minutes: int


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    values = environ if env is None else env
    database_host = values.get("ALPHADB_POSTGRES_HOST", DEFAULT_DATABASE_HOST)
    database_port = values.get("ALPHADB_POSTGRES_PORT", DEFAULT_DATABASE_PORT)
    default_database_url = (
        f"postgresql://{DEFAULT_DATABASE_USER}:{DEFAULT_DATABASE_PASSWORD}"
        f"@{database_host}:{database_port}/{DEFAULT_DATABASE_NAME}"
    )
    return Settings(
        environment=values.get("ALPHADB_ENV", "local"),
        database_url=values.get("DATABASE_URL", default_database_url),
        streamlit_port=values.get("ALPHADB_STREAMLIT_PORT", "8501"),
        runtime_mode=values.get("ALPHADB_RUNTIME_MODE", "fixture"),
        enable_live_orders=values.get("ALPHADB_ENABLE_LIVE_ORDERS") == "1",
        human_cutover_approved=values.get("ALPHADB_HUMAN_CUTOVER_APPROVED") == "1",
        kalshi_base_url=values.get("ALPHADB_KALSHI_BASE_URL", DEFAULT_KALSHI_BASE_URL),
        kalshi_ws_url=values.get("ALPHADB_KALSHI_WS_URL"),
        kalshi_api_key_id=values.get("KALSHI_API_KEY_ID"),
        kalshi_private_key_path=values.get("KALSHI_PRIVATE_KEY_PATH"),
        enable_live_ws_smoke=values.get("ALPHADB_ENABLE_LIVE_WS_SMOKE") == "1",
        enable_live_order_smoke=values.get("ALPHADB_ENABLE_LIVE_ORDER_SMOKE") == "1",
        artifact_root=values.get("ALPHADB_ARTIFACT_ROOT"),
        current_mvp_artifact_config=values.get("ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG"),
        coinbase_product_id=values.get("ALPHADB_COINBASE_PRODUCT_ID", "BTC-USD"),
        coinbase_granularity_seconds=int(values.get("ALPHADB_COINBASE_GRANULARITY_SECONDS", "60")),
        coinbase_lookback_minutes=int(values.get("ALPHADB_COINBASE_LOOKBACK_MINUTES", "60")),
    )
