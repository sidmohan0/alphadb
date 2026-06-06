from __future__ import annotations

from datetime import UTC, datetime

from alphadb.config import settings_from_env
from alphadb.portfolio import (
    CachedPortfolioBalanceProvider,
    portfolio_balance_from_response,
)


class FakePortfolioClient:
    def __init__(self):
        self.calls = 0

    def get_balance(self, *, settings):
        self.calls += 1
        return {"balance": 6789, "portfolio_value": 12345}


def test_portfolio_balance_parses_cash_assets_and_total_balance() -> None:
    balance = portfolio_balance_from_response(
        {"balance": 6789, "portfolio_value": 12345},
        observed_at_utc=datetime(2026, 6, 6, 20, tzinfo=UTC),
    )

    assert balance.status == "ok"
    assert balance.cash_dollars == 67.89
    assert balance.assets_dollars == 123.45
    assert balance.portfolio_balance_dollars == 191.34
    assert balance.stale is False


def test_portfolio_balance_cache_reuses_recent_exchange_read() -> None:
    client = FakePortfolioClient()
    provider = CachedPortfolioBalanceProvider(client, cache_seconds=30)
    settings = settings_from_env(
        {
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
    )

    first = provider.payload(settings)
    second = provider.payload(settings)

    assert client.calls == 1
    assert first["portfolio_balance_dollars"] == 191.34
    assert second["cash_dollars"] == 67.89


def test_portfolio_balance_reports_unknown_without_credentials() -> None:
    provider = CachedPortfolioBalanceProvider(FakePortfolioClient())

    payload = provider.payload(settings_from_env())

    assert payload["status"] == "unavailable"
    assert payload["portfolio_balance_dollars"] is None
    assert payload["cash_dollars"] is None
    assert payload["assets_dollars"] is None
    assert payload["stale"] is True
    assert payload["detail"] == "missing_kalshi_credentials"
