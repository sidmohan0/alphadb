"""Live fair-value decision-row collection for report-only experiments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from alphadb.collectors.coinbase import (
    CoinbaseClient,
    FixtureCoinbaseClient,
    HttpCoinbaseClient,
    build_external_price_features,
    normalize_coinbase_candles,
)
from alphadb.collectors.kalshi_rest import (
    FixtureKalshiRestClient,
    HttpKalshiRestClient,
    KalshiRestClient,
    eligible_markets,
    parse_kalshi_datetime,
)
from alphadb.config import Settings, settings_from_env
from alphadb.markets.registry import default_market_registry
from alphadb.model_evaluation.fair_value_model import (
    ThresholdVolatilityFairValueConfig,
    build_threshold_volatility_fair_value_rows,
    parse_threshold_from_text,
)
from alphadb.model_evaluation.metrics import optional_float

FAIR_VALUE_DECISION_ROWS_SCHEMA = "kxbtc_fair_value_decision_rows.v1"


@dataclass(frozen=True)
class FairValueDecisionRowCollectorConfig:
    series: str = "KXBTC15M"
    status: str = "open"
    max_markets: int = 5
    run_id: str | None = None
    source_mode: str = "fixture"
    coinbase_source_mode: str = "fixture"
    model_config: ThresholdVolatilityFairValueConfig = ThresholdVolatilityFairValueConfig()
    include_coinbase_features: bool = True
    include_fair_value_score: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "series": self.series,
            "status": self.status,
            "max_markets": self.max_markets,
            "run_id": self.run_id,
            "source_mode": self.source_mode,
            "coinbase_source_mode": self.coinbase_source_mode,
            "model_config": self.model_config.as_dict(),
            "include_coinbase_features": self.include_coinbase_features,
            "include_fair_value_score": self.include_fair_value_score,
        }


@dataclass(frozen=True)
class FairValueDecisionRowsResult:
    schema_version: str
    run_id: str
    generated_at: datetime
    config: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    errors: tuple[Mapping[str, Any], ...]
    orders_placed: int = 0

    def as_dict(self) -> dict[str, Any]:
        decisions = [row for row in self.rows if row.get("row_type") == "decision"]
        skips = [row for row in self.rows if row.get("row_type") == "skip"]
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "generated_at": self.generated_at.isoformat(),
            "config": dict(self.config),
            "counts": {
                "rows": len(self.rows),
                "decisions": len(decisions),
                "skips": len(skips),
                "errors": len(self.errors),
                "orders_placed": self.orders_placed,
            },
            "skip_reasons": summarize_skip_reasons(skips),
            "rows": [dict(row) for row in self.rows],
            "errors": [dict(error) for error in self.errors],
            "orders_placed": self.orders_placed,
        }


class FairValueDecisionRowCollector:
    def __init__(
        self,
        *,
        kalshi_client: KalshiRestClient,
        coinbase_client: CoinbaseClient,
        settings: Settings | None = None,
        config: FairValueDecisionRowCollectorConfig | None = None,
    ):
        self.settings = settings or settings_from_env()
        self.config = config or FairValueDecisionRowCollectorConfig()
        self.kalshi_client = kalshi_client
        self.coinbase_client = coinbase_client
        self.spec = default_market_registry().get(self.config.series)

    def collect(self, *, now: datetime | None = None) -> FairValueDecisionRowsResult:
        generated_at = ensure_utc(now or datetime.now(UTC))
        run_id = self.config.run_id or f"fv_report_{generated_at.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        rows: list[Mapping[str, Any]] = []
        errors: list[Mapping[str, Any]] = []
        try:
            payload = self.kalshi_client.list_markets(
                series_ticker=self.spec.discovery_rules.series_ticker,
                status=self.config.status,
                limit=self.config.max_markets,
            )
            markets = eligible_markets(self.spec, payload.get("markets", []))
        except Exception as exc:
            markets = []
            errors.append({"stage": "discover_markets", "message": str(exc)})

        for market in markets[: self.config.max_markets]:
            rows.append(self._collect_market_row(run_id=run_id, market=market, now=generated_at))
        return FairValueDecisionRowsResult(
            schema_version=FAIR_VALUE_DECISION_ROWS_SCHEMA,
            run_id=run_id,
            generated_at=generated_at,
            config={**self.config.as_dict(), "run_id": run_id},
            rows=tuple(rows),
            errors=tuple(errors),
            orders_placed=0,
        )

    def _collect_market_row(
        self,
        *,
        run_id: str,
        market: Mapping[str, Any],
        now: datetime,
    ) -> Mapping[str, Any]:
        market_ticker = str(market.get("ticker") or "")
        base = {
            "row_schema_version": FAIR_VALUE_DECISION_ROWS_SCHEMA,
            "run_id": run_id,
            "ticker": market_ticker,
            "market_ticker": market_ticker,
            "series": self.spec.series,
            "decision_timestamp": now.isoformat(),
            "kalshi_received_at": now.isoformat(),
            "config_id": fair_value_config_id(self.config),
            "source_mode": self.config.source_mode,
            "coinbase_source_mode": self.config.coinbase_source_mode,
            "orders_placed": 0,
        }
        if not market_ticker:
            return skip_row(base, "missing_market_ticker")
        open_time = parse_kalshi_datetime(market.get("open_time"), now)
        close_time = parse_kalshi_datetime(
            market.get("close_time")
            or market.get("expected_expiration_time")
            or market.get("expiration_time"),
            open_time + timedelta(minutes=self.spec.horizon_minutes),
        )
        market_list_yes_ask = quote_price(market, ("yes_ask_dollars", "yes_ask", "yes_price"))
        market_list_no_ask = quote_price(market, ("no_ask_dollars", "no_ask", "no_price"))
        threshold = payout_threshold(market)
        market_metadata_updated_at = parse_kalshi_datetime(market.get("updated_time"), now)
        try:
            orderbook = self.kalshi_client.get_orderbook(market_ticker)
        except Exception as exc:
            return skip_row(base, "missing_quote", error_type=type(exc).__name__, error_message=str(exc))
        quote_observed_at = now
        if threshold is None:
            return skip_row(
                {
                    **base,
                    "market_open_time": open_time.isoformat(),
                    "close_time": close_time.isoformat(),
                    "yes_ask": market_list_yes_ask,
                    "no_ask": market_list_no_ask,
                    "quote_observed_at": quote_observed_at.isoformat(),
                    "market_metadata_updated_at": market_metadata_updated_at.isoformat(),
                    "market_list_yes_ask": market_list_yes_ask,
                    "market_list_no_ask": market_list_no_ask,
                    "orderbook_observed": True,
                    "orderbook_shape": orderbook_shape(orderbook),
                },
                "unsupported_market_shape",
            )
        executable_quotes = executable_orderbook_quotes(orderbook)
        yes_ask = executable_quotes["yes_ask"]
        no_ask = executable_quotes["no_ask"]
        if yes_ask is None or no_ask is None:
            return skip_row(
                {
                    **base,
                    "market_open_time": open_time.isoformat(),
                    "close_time": close_time.isoformat(),
                    "quote_observed_at": quote_observed_at.isoformat(),
                    "market_metadata_updated_at": market_metadata_updated_at.isoformat(),
                    "market_list_yes_ask": market_list_yes_ask,
                    "market_list_no_ask": market_list_no_ask,
                    "orderbook_observed": True,
                    "orderbook_shape": orderbook_shape(orderbook),
                    "quote_source": "kalshi_orderbook",
                },
                "missing_orderbook_quote",
            )

        decision_input = {
            **base,
            "row_type": "decision",
            "market_open_time": open_time.isoformat(),
            "close_time": close_time.isoformat(),
            "time_to_close_seconds": max(0.0, (close_time - now).total_seconds()),
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "quote_observed_at": quote_observed_at.isoformat(),
            "quote_source": "kalshi_orderbook",
            "market_metadata_updated_at": market_metadata_updated_at.isoformat(),
            "market_list_yes_ask": market_list_yes_ask,
            "market_list_no_ask": market_list_no_ask,
            "payout_threshold": threshold,
            "orderbook_observed": True,
            "orderbook_shape": orderbook_shape(orderbook),
            **executable_quotes,
        }
        if not self.config.include_coinbase_features:
            return {
                **decision_input,
                "fair_value_status": "not_applicable",
                "fair_value_skip_reason": None,
                "p_yes": None,
            }
        try:
            features, feature_metadata = self._coinbase_features(now)
        except Exception as exc:
            return skip_row(
                decision_input,
                "missing_feature_data",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        decision_input = {**decision_input, **features, **feature_metadata}
        if not self.config.include_fair_value_score:
            return {
                **decision_input,
                "fair_value_status": "not_applicable",
                "fair_value_skip_reason": None,
                "p_yes": None,
            }
        scored = build_threshold_volatility_fair_value_rows(
            [decision_input],
            config=self.config.model_config,
        )[0]
        if scored.get("fair_value_status") != "complete":
            return skip_row(
                scored,
                str(scored.get("fair_value_skip_reason") or "missing_feature_data"),
            )
        return scored

    def _coinbase_features(self, decision_timestamp: datetime) -> tuple[dict[str, float], dict[str, Any]]:
        decision_ts = ensure_utc(decision_timestamp)
        raw = self.coinbase_client.get_candles(
            product_id=self.settings.coinbase_product_id,
            start=decision_ts - timedelta(minutes=self.settings.coinbase_lookback_minutes),
            end=decision_ts,
            granularity_seconds=self.settings.coinbase_granularity_seconds,
        )
        candles = normalize_coinbase_candles(raw)
        eligible = [candle for candle in candles if candle["timestamp"] <= decision_ts]
        if not eligible:
            raise ValueError("no Coinbase candles at or before decision timestamp")
        latest = eligible[-1]
        features = build_external_price_features(eligible)
        return features, {
            "coinbase_product_id": self.settings.coinbase_product_id,
            "coinbase_max_source_event_timestamp": latest["timestamp"].isoformat(),
            "coinbase_source_lag_ms": int((decision_ts - latest["timestamp"]).total_seconds() * 1000),
            "no_lookahead_source_check": latest["timestamp"] <= decision_ts,
        }


def build_fixture_fair_value_decision_rows(
    *,
    now: datetime | None = None,
    max_markets: int = 5,
) -> dict[str, Any]:
    settings = settings_from_env()
    result = FairValueDecisionRowCollector(
        kalshi_client=FixtureKalshiRestClient(),
        coinbase_client=FixtureCoinbaseClient(),
        settings=settings,
        config=FairValueDecisionRowCollectorConfig(max_markets=max_markets),
    ).collect(now=now)
    return result.as_dict()


def make_kalshi_client(source: str, settings: Settings) -> KalshiRestClient:
    if source == "fixture":
        return FixtureKalshiRestClient()
    if source == "kalshi-public":
        return HttpKalshiRestClient(settings.kalshi_base_url)
    raise ValueError(f"unsupported Kalshi source: {source}")


def make_coinbase_client(source: str) -> CoinbaseClient:
    if source == "fixture":
        return FixtureCoinbaseClient()
    if source == "coinbase-live":
        return HttpCoinbaseClient()
    raise ValueError(f"unsupported Coinbase source: {source}")


def skip_row(
    base: Mapping[str, Any],
    reason: str,
    *,
    error_type: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    row = dict(base)
    row.update(
        {
            "row_type": "skip",
            "skip_reason": reason,
            "fair_value_status": "skipped",
            "fair_value_skip_reason": reason,
            "p_yes": None,
        }
    )
    if error_type is not None:
        row["error_type"] = error_type
    if error_message is not None:
        row["error_message"] = error_message
    return row


def payout_threshold(market: Mapping[str, Any]) -> float | None:
    for key in (
        "payout_threshold",
        "strike",
        "strike_price",
        "floor_strike",
        "cap_strike",
        "target_price",
    ):
        value = optional_float(market.get(key))
        if value is not None:
            return value
    return parse_threshold_from_text(market)


def quote_price(market: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = optional_float(market.get(key))
        if value is None:
            continue
        return value / 100.0 if value > 1.0 else value
    return None


def executable_orderbook_quotes(orderbook: Mapping[str, Any]) -> dict[str, float | None]:
    payload = orderbook_payload(orderbook)
    yes_bid = first_level_contract_price(payload.get("yes_dollars") or payload.get("yes") or [])
    no_bid = first_level_contract_price(payload.get("no_dollars") or payload.get("no") or [])
    yes_ask = round(1.0 - no_bid, 6) if no_bid is not None else None
    no_ask = round(1.0 - yes_bid, 6) if yes_bid is not None else None
    return {
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "orderbook_yes_bid": yes_bid,
        "orderbook_no_bid": no_bid,
    }


def orderbook_payload(orderbook: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(orderbook.get("orderbook_fp"), Mapping):
        return orderbook["orderbook_fp"]
    if isinstance(orderbook.get("orderbook"), Mapping):
        nested = orderbook["orderbook"]
        if isinstance(nested.get("orderbook_fp"), Mapping):
            return nested["orderbook_fp"]
        return nested
    return orderbook


def first_level_contract_price(levels: Any) -> float | None:
    price = first_level_price(levels)
    if price is None:
        return None
    price = price / 100.0 if price > 1.0 else price
    if price <= 0.0 or price >= 1.0:
        return None
    return round(price, 6)


def first_level_price(levels: Any) -> float | None:
    if not levels:
        return None
    first = levels[0]
    if not isinstance(first, Sequence) or isinstance(first, (str, bytes)) or not first:
        return None
    return optional_float(first[0])


def orderbook_shape(orderbook: Mapping[str, Any]) -> dict[str, Any]:
    payload = orderbook_payload(orderbook)
    yes = (payload.get("yes_dollars") or payload.get("yes")) if isinstance(payload, Mapping) else None
    no = (payload.get("no_dollars") or payload.get("no")) if isinstance(payload, Mapping) else None
    return {
        "yes_levels": len(yes) if isinstance(yes, list) else 0,
        "no_levels": len(no) if isinstance(no, list) else 0,
    }


def summarize_skip_reasons(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reasons = sorted({str(row.get("skip_reason")) for row in rows})
    return [
        {
            "reason": reason,
            "count": sum(1 for row in rows if str(row.get("skip_reason")) == reason),
        }
        for reason in reasons
    ]


def fair_value_config_id(config: FairValueDecisionRowCollectorConfig) -> str:
    return (
        f"{config.series}:max_markets={config.max_markets}:"
        f"source={config.source_mode}:coinbase={config.coinbase_source_mode}:"
        f"model={config.model_config.probability_column}"
    )


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
