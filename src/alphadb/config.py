"""Runtime configuration for AlphaDB services."""

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
DEFAULT_AWS_REGION = "us-east-2"
DEFAULT_DASHBOARD_COOKIE_NAME = "alphadb_dashboard_auth"
DEFAULT_DASHBOARD_COOKIE_TTL_SECONDS = 60 * 60 * 24 * 7
DEFAULT_X_API_BASE_URL = "https://api.x.com"
DEFAULT_X_API_OUTPUT_ROOT = "artifacts"


class SettingsError(ValueError):
    """Raised when environment configuration is malformed."""


@dataclass(frozen=True)
class Settings:
    environment: str
    aws_region: str
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
    x_api_base_url: str = DEFAULT_X_API_BASE_URL
    x_api_bearer_token: str | None = None
    x_api_daily_cap_usd: float | None = None
    x_api_default_output_root: str = DEFAULT_X_API_OUTPUT_ROOT
    live_stake_cap_dollars: float = 1.0
    max_daily_loss_dollars: float = 10.0
    min_ev_dollars: float = 0.0
    strategy_poll_seconds: int = 60
    dashboard_pin: str | None = None
    dashboard_cookie_secret: str | None = None
    dashboard_cookie_ttl_seconds: int = DEFAULT_DASHBOARD_COOKIE_TTL_SECONDS
    dashboard_cookie_name: str = DEFAULT_DASHBOARD_COOKIE_NAME

    @property
    def dashboard_auth_configured(self) -> bool:
        return bool(self.dashboard_pin)


def _value(values: Mapping[str, str], key: str, default: str | None = None) -> str | None:
    value = values.get(key, default)
    if value == "":
        return None
    return value


def _bool(values: Mapping[str, str], key: str) -> bool:
    return values.get(key) == "1"


def _int(values: Mapping[str, str], key: str, default: str) -> int:
    raw = values.get(key, default)
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be an integer: {raw!r}") from exc


def _float(values: Mapping[str, str], key: str, default: str) -> float:
    raw = values.get(key, default)
    try:
        return float(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be a number: {raw!r}") from exc


def _optional_float(values: Mapping[str, str], key: str) -> float | None:
    raw = _value(values, key)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be a number: {raw!r}") from exc


def validate_settings(settings: Settings) -> Settings:
    if not settings.streamlit_port.isdigit():
        raise SettingsError(f"ALPHADB_STREAMLIT_PORT must be a port number: {settings.streamlit_port!r}")
    if settings.dashboard_pin is not None:
        if not (settings.dashboard_pin.isdigit() and len(settings.dashboard_pin) == 4):
            raise SettingsError("ALPHADB_DASHBOARD_PIN must be exactly four digits")
        if not settings.dashboard_cookie_secret:
            raise SettingsError(
                "ALPHADB_DASHBOARD_COOKIE_SECRET is required when ALPHADB_DASHBOARD_PIN is set"
            )
    if settings.dashboard_cookie_secret and settings.dashboard_cookie_ttl_seconds <= 0:
        raise SettingsError("ALPHADB_DASHBOARD_COOKIE_TTL_SECONDS must be positive")
    if not settings.dashboard_cookie_name:
        raise SettingsError("ALPHADB_DASHBOARD_COOKIE_NAME must not be empty")
    if settings.x_api_daily_cap_usd is not None and settings.x_api_daily_cap_usd <= 0:
        raise SettingsError("ALPHADB_X_API_DAILY_CAP_USD must be positive when set")
    if not settings.x_api_default_output_root:
        raise SettingsError("ALPHADB_X_API_DEFAULT_OUTPUT_ROOT must not be empty")
    return settings


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    values = environ if env is None else env
    database_host = values.get("ALPHADB_POSTGRES_HOST", DEFAULT_DATABASE_HOST)
    database_port = values.get("ALPHADB_POSTGRES_PORT", DEFAULT_DATABASE_PORT)
    default_database_url = (
        f"postgresql://{DEFAULT_DATABASE_USER}:{DEFAULT_DATABASE_PASSWORD}"
        f"@{database_host}:{database_port}/{DEFAULT_DATABASE_NAME}"
    )
    settings = Settings(
        environment=values.get("ALPHADB_ENV", "local"),
        aws_region=values.get("AWS_REGION", values.get("ALPHADB_AWS_REGION", DEFAULT_AWS_REGION)),
        database_url=values.get("DATABASE_URL", default_database_url),
        streamlit_port=values.get("ALPHADB_STREAMLIT_PORT", "8501"),
        runtime_mode=values.get("ALPHADB_RUNTIME_MODE", "fixture"),
        enable_live_orders=_bool(values, "ALPHADB_ENABLE_LIVE_ORDERS"),
        human_cutover_approved=_bool(values, "ALPHADB_HUMAN_CUTOVER_APPROVED"),
        kalshi_base_url=values.get("ALPHADB_KALSHI_BASE_URL", DEFAULT_KALSHI_BASE_URL),
        kalshi_ws_url=_value(values, "ALPHADB_KALSHI_WS_URL"),
        kalshi_api_key_id=_value(values, "KALSHI_API_KEY_ID"),
        kalshi_private_key_path=_value(values, "KALSHI_PRIVATE_KEY_PATH"),
        enable_live_ws_smoke=_bool(values, "ALPHADB_ENABLE_LIVE_WS_SMOKE"),
        enable_live_order_smoke=_bool(values, "ALPHADB_ENABLE_LIVE_ORDER_SMOKE"),
        artifact_root=_value(values, "ALPHADB_ARTIFACT_ROOT"),
        current_mvp_artifact_config=_value(values, "ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG"),
        coinbase_product_id=values.get("ALPHADB_COINBASE_PRODUCT_ID", "BTC-USD"),
        coinbase_granularity_seconds=_int(values, "ALPHADB_COINBASE_GRANULARITY_SECONDS", "60"),
        coinbase_lookback_minutes=_int(values, "ALPHADB_COINBASE_LOOKBACK_MINUTES", "60"),
        x_api_base_url=values.get("ALPHADB_X_API_BASE_URL", DEFAULT_X_API_BASE_URL),
        x_api_bearer_token=_value(values, "ALPHADB_X_BEARER_TOKEN")
        or _value(values, "X_BEARER_TOKEN"),
        x_api_daily_cap_usd=_optional_float(values, "ALPHADB_X_API_DAILY_CAP_USD"),
        x_api_default_output_root=values.get(
            "ALPHADB_X_API_DEFAULT_OUTPUT_ROOT",
            DEFAULT_X_API_OUTPUT_ROOT,
        ),
        live_stake_cap_dollars=_float(values, "ALPHADB_LIVE_STAKE_CAP_DOLLARS", "1.0"),
        max_daily_loss_dollars=_float(values, "ALPHADB_MAX_DAILY_LOSS_DOLLARS", "10.0"),
        min_ev_dollars=_float(values, "ALPHADB_MIN_EV_DOLLARS", "0.0"),
        strategy_poll_seconds=_int(values, "ALPHADB_STRATEGY_POLL_SECONDS", "60"),
        dashboard_pin=_value(values, "ALPHADB_DASHBOARD_PIN"),
        dashboard_cookie_secret=_value(values, "ALPHADB_DASHBOARD_COOKIE_SECRET"),
        dashboard_cookie_ttl_seconds=_int(
            values,
            "ALPHADB_DASHBOARD_COOKIE_TTL_SECONDS",
            str(DEFAULT_DASHBOARD_COOKIE_TTL_SECONDS),
        ),
        dashboard_cookie_name=values.get(
            "ALPHADB_DASHBOARD_COOKIE_NAME", DEFAULT_DASHBOARD_COOKIE_NAME
        ),
    )
    return validate_settings(settings)
