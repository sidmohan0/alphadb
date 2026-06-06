"""Exchange portfolio balance reads for Cockpit status display."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib import request

from alphadb.config import Settings
from alphadb.live_orders import signed_kalshi_headers


BALANCE_PATH = "/portfolio/balance"
BALANCE_CACHE_SECONDS = 30.0
BALANCE_STALE_SECONDS = 60.0


class PortfolioBalanceError(RuntimeError):
    """Raised when the exchange balance cannot be read."""


class KalshiPortfolioClient(Protocol):
    def get_balance(self, *, settings: Settings) -> Mapping[str, Any]:
        """Return authenticated Kalshi balance payload."""


class HttpKalshiPortfolioClient:
    path = BALANCE_PATH

    def get_balance(self, *, settings: Settings) -> Mapping[str, Any]:
        url = settings.kalshi_base_url.rstrip("/") + self.path
        http_request = request.Request(
            url,
            headers=signed_kalshi_headers(settings=settings, method="GET", path=self.path),
            method="GET",
        )
        with request.urlopen(http_request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise PortfolioBalanceError("Kalshi balance response was not a JSON object")
        return payload


@dataclass(frozen=True)
class PortfolioBalance:
    status: str
    source: str
    portfolio_balance_dollars: float | None
    cash_dollars: float | None
    assets_dollars: float | None
    observed_at_utc: datetime | None
    stale: bool
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "portfolio_balance_dollars": self.portfolio_balance_dollars,
            "cash_dollars": self.cash_dollars,
            "assets_dollars": self.assets_dollars,
            "observed_at_utc": self.observed_at_utc.isoformat()
            if self.observed_at_utc
            else None,
            "stale": self.stale,
            "detail": self.detail,
        }


@dataclass
class CachedPortfolioBalanceProvider:
    client: KalshiPortfolioClient
    cache_seconds: float = BALANCE_CACHE_SECONDS
    stale_seconds: float = BALANCE_STALE_SECONDS

    _balance: PortfolioBalance | None = None
    _loaded_monotonic: float | None = None

    def payload(self, settings: Settings) -> dict[str, Any]:
        now_monotonic = time.monotonic()
        if self._balance is not None and self._loaded_monotonic is not None:
            age = now_monotonic - self._loaded_monotonic
            if age <= self.cache_seconds:
                return self._with_stale_flag(self._balance, age).as_dict()
        balance = read_portfolio_balance(settings=settings, client=self.client)
        self._balance = balance
        self._loaded_monotonic = now_monotonic
        return balance.as_dict()

    def _with_stale_flag(self, balance: PortfolioBalance, age: float) -> PortfolioBalance:
        return PortfolioBalance(
            status=balance.status,
            source=balance.source,
            portfolio_balance_dollars=balance.portfolio_balance_dollars,
            cash_dollars=balance.cash_dollars,
            assets_dollars=balance.assets_dollars,
            observed_at_utc=balance.observed_at_utc,
            stale=balance.stale or age > self.stale_seconds,
            detail=balance.detail,
        )


_DEFAULT_BALANCE_PROVIDER = CachedPortfolioBalanceProvider(HttpKalshiPortfolioClient())


def cached_portfolio_balance_payload(settings: Settings) -> dict[str, Any]:
    return _DEFAULT_BALANCE_PROVIDER.payload(settings)


def read_portfolio_balance(
    *,
    settings: Settings,
    client: KalshiPortfolioClient,
) -> PortfolioBalance:
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        return unavailable_balance("missing_kalshi_credentials")
    try:
        return portfolio_balance_from_response(
            client.get_balance(settings=settings),
            observed_at_utc=datetime.now(UTC),
        )
    except Exception as exc:
        return unavailable_balance(str(exc) or exc.__class__.__name__)


def portfolio_balance_from_response(
    payload: Mapping[str, Any],
    *,
    observed_at_utc: datetime,
) -> PortfolioBalance:
    cash = _cents_field(payload, "balance")
    portfolio_value = _cents_field(payload, "portfolio_value")
    if cash is None:
        raise PortfolioBalanceError("balance response missing balance")
    if portfolio_value is None:
        raise PortfolioBalanceError("balance response missing portfolio_value")
    assets = portfolio_value
    portfolio_balance = cash + assets
    return PortfolioBalance(
        status="ok",
        source="kalshi",
        portfolio_balance_dollars=round(portfolio_balance, 2),
        cash_dollars=round(cash, 2),
        assets_dollars=round(assets, 2),
        observed_at_utc=observed_at_utc,
        stale=False,
    )


def unavailable_balance(detail: str) -> PortfolioBalance:
    return PortfolioBalance(
        status="unavailable",
        source="kalshi",
        portfolio_balance_dollars=None,
        cash_dollars=None,
        assets_dollars=None,
        observed_at_utc=None,
        stale=True,
        detail=detail,
    )


def _cents_field(payload: Mapping[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    return float(value) / 100.0
