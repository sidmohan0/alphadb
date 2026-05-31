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
    kalshi_base_url: str


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
        kalshi_base_url=values.get("ALPHADB_KALSHI_BASE_URL", DEFAULT_KALSHI_BASE_URL),
    )
