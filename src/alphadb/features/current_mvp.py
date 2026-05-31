"""Current MVP KXBTC15M feature-row parity builder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from alphadb.artifacts import PinnedModelPolicy
from alphadb.events.log import RawEventLog, canonical_payload_hash
from alphadb.features.ledger import (
    FeatureLedgerRepository,
    FeatureRow,
    MissingFeatureEventsError,
    NoLookaheadViolationError,
    ensure_utc,
    event_source_timestamp,
)
from alphadb.model_registry.registry import ModelRegistryRepository
from alphadb.state.repository import OperationalStateRepository

CURRENT_MVP_REQUIRED_SCHEMAS = (
    "kalshi.market_snapshot.v1",
    "kalshi.orderbook_snapshot.v1",
    "kalshi.candlestick_snapshot.v1",
    "kalshi.trade_snapshot.v1",
    "coinbase.btc_usd_features.v1",
)


class MissingCurrentMvpFeatureError(ValueError):
    """Raised when Current MVP feature-schema columns cannot be satisfied."""


@dataclass(frozen=True)
class CurrentMvpFeatureBuild:
    feature_row: FeatureRow
    model_ready_values: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_row": self.feature_row.as_dict(),
            "model_ready_values": list(self.model_ready_values),
        }


class CurrentMvpFeatureRowBuilder:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.raw_events = RawEventLog(database_url)
        self.ledger = FeatureLedgerRepository(database_url)
        self.models = ModelRegistryRepository(database_url)

    def build(
        self,
        *,
        run_id: str,
        market_ticker: str,
        model_id: str,
        policy: PinnedModelPolicy,
        decision_timestamp: datetime,
    ) -> CurrentMvpFeatureBuild:
        OperationalStateRepository(self.database_url).apply_migrations()
        model = self.models.get(model_id)
        decision_ts = ensure_utc(decision_timestamp)
        events = list(self.raw_events.replay_events(run_id=run_id, market_ticker=market_ticker))
        selected = latest_events_before_decision(
            events=events,
            required_schemas=CURRENT_MVP_REQUIRED_SCHEMAS,
            decision_timestamp=decision_ts,
        )
        max_source_ts = max(event_source_timestamp(event) for event in selected)
        if max_source_ts > decision_ts:
            raise NoLookaheadViolationError(
                "max_source_event_timestamp is after decision_timestamp: "
                f"{max_source_ts.isoformat()} > {decision_ts.isoformat()}"
            )
        values = build_current_mvp_feature_values(
            selected,
            feature_columns=policy.feature_columns,
            decision_timestamp=decision_ts,
        )
        model_ready_values = tuple(float(values[column]) for column in policy.feature_columns)
        source_event_ids = tuple(str(event["raw_event_id"]) for event in selected)
        row_hash = canonical_payload_hash(
            {
                "run_id": run_id,
                "market_ticker": market_ticker,
                "model_id": model_id,
                "decision_timestamp": decision_ts.isoformat(),
                "feature_version": model.feature_version,
                "dataset_id": model.dataset_id,
                "feature_values": values,
                "source_event_ids": source_event_ids,
            }
        )
        row = FeatureRow(
            feature_row_id=f"feature_{uuid4().hex[:12]}",
            run_id=run_id,
            market_ticker=market_ticker,
            model_id=model_id,
            decision_timestamp=decision_ts,
            max_source_event_timestamp=max_source_ts,
            source_lag_ms=int((decision_ts - max_source_ts).total_seconds() * 1000),
            feature_version=model.feature_version,
            calibration_version=model.calibration_version,
            dataset_id=model.dataset_id,
            feature_values=values,
            source_event_ids=source_event_ids,
            row_hash=row_hash,
            metadata={
                "builder": "current_mvp_feature_parity.v1",
                "feature_schema_sha256": policy.feature_schema_sha256,
                "model_artifact_sha256": policy.model_artifact_sha256,
                "required_schemas": list(CURRENT_MVP_REQUIRED_SCHEMAS),
            },
        )
        stored = self.ledger.upsert_immutable(row)
        return CurrentMvpFeatureBuild(feature_row=stored, model_ready_values=model_ready_values)


def latest_events_before_decision(
    *,
    events: Sequence[Mapping[str, Any]],
    required_schemas: Sequence[str],
    decision_timestamp: datetime,
) -> list[Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for event in events:
        schema = str(event["schema_version"])
        if schema not in required_schemas:
            continue
        source_ts = event_source_timestamp(event)
        current = latest.get(schema)
        if current is None or (source_ts, str(event["raw_event_id"])) > (
            event_source_timestamp(current),
            str(current["raw_event_id"]),
        ):
            latest[schema] = event
    missing = [schema for schema in required_schemas if schema not in latest]
    if missing:
        raise MissingFeatureEventsError(f"missing required raw event schemas: {', '.join(missing)}")
    selected = [latest[schema] for schema in required_schemas]
    future = [event for event in selected if event_source_timestamp(event) > decision_timestamp]
    if future:
        raise NoLookaheadViolationError("latest required source event is after decision timestamp")
    return selected


def build_current_mvp_feature_values(
    events: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    decision_timestamp: datetime,
) -> dict[str, float]:
    by_schema = {str(event["schema_version"]): dict(event["payload"]) for event in events}
    market = unwrap_payload(by_schema["kalshi.market_snapshot.v1"], "market")
    orderbook = unwrap_payload(by_schema["kalshi.orderbook_snapshot.v1"], "orderbook")
    candle = unwrap_payload(by_schema["kalshi.candlestick_snapshot.v1"], "candlestick")
    trade = unwrap_payload(by_schema["kalshi.trade_snapshot.v1"], "trade")
    coinbase = dict(by_schema["coinbase.btc_usd_features.v1"].get("feature_values", {}))
    open_time = parse_datetime(market.get("open_time"))
    close_time = parse_datetime(
        market.get("close_time")
        or market.get("expected_expiration_time")
        or market.get("expiration_time")
    )
    quotes = quote_values(market, orderbook)
    base: dict[str, Any] = {
        "decision_minute_offset": int((decision_timestamp - open_time).total_seconds() // 60)
        if open_time
        else None,
        "time_since_open_seconds": (decision_timestamp - open_time).total_seconds()
        if open_time
        else None,
        "time_to_close_seconds": (close_time - decision_timestamp).total_seconds()
        if close_time
        else None,
        "price_close_dollars": value_or(candle, "price_close_dollars", "close"),
        "yes_bid_close_dollars": value_or(candle, "yes_bid_close_dollars", "yes_bid"),
        "yes_ask_close_dollars": value_or(candle, "yes_ask_close_dollars", "yes_ask"),
        "no_bid_close_dollars": value_or(candle, "no_bid_close_dollars", "no_bid"),
        "no_ask_close_dollars": value_or(candle, "no_ask_close_dollars", "no_ask"),
        "volume_fp": value_or(candle, "volume_fp", "volume"),
        "open_interest_fp": candle.get("open_interest_fp"),
        "last_trade_yes_price_dollars": value_or(trade, "yes_price_dollars", "yes_price"),
        "last_trade_no_price_dollars": value_or(trade, "no_price_dollars", "no_price"),
        "last_trade_price_dollars": value_or(trade, "price_dollars", "price"),
        "last_trade_count_fp": value_or(trade, "count_fp", "count"),
        "yes_bid": quotes["yes_bid"],
        "yes_ask": quotes["yes_ask"],
        "no_bid": quotes["no_bid"],
        "no_ask": quotes["no_ask"],
        "yes_bid_dollars": quotes["yes_bid"],
        "yes_ask_dollars": quotes["yes_ask"],
        "no_bid_dollars": quotes["no_bid"],
        "no_ask_dollars": quotes["no_ask"],
    }
    base.update(coinbase)

    missing: list[str] = []
    values: dict[str, float] = {}
    for column in feature_columns:
        numeric = optional_float(base.get(column))
        if numeric is None:
            missing.append(column)
        else:
            values[column] = numeric
    if missing:
        raise MissingCurrentMvpFeatureError(
            f"missing Current MVP feature columns: {', '.join(sorted(missing))}"
        )

    for quote_column in ("yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars"):
        if optional_float(base.get(quote_column)) is not None:
            values[quote_column] = float(base[quote_column])
    return values


def unwrap_payload(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if isinstance(value, Mapping):
        return dict(value)
    return dict(payload)


def quote_values(
    market: Mapping[str, Any],
    orderbook_payload: Mapping[str, Any],
) -> dict[str, float | None]:
    orderbook = orderbook_payload.get("orderbook_fp") if isinstance(orderbook_payload, Mapping) else {}
    if isinstance(orderbook, Mapping):
        yes_levels = orderbook.get("yes_dollars") or orderbook.get("yes") or []
        no_levels = orderbook.get("no_dollars") or orderbook.get("no") or []
    else:
        yes_levels = []
        no_levels = []
    return {
        "yes_bid": optional_float(market.get("yes_bid_dollars")) or first_level_price(yes_levels),
        "yes_ask": optional_float(market.get("yes_ask_dollars")),
        "no_bid": optional_float(market.get("no_bid_dollars")) or first_level_price(no_levels),
        "no_ask": optional_float(market.get("no_ask_dollars")),
    }


def first_level_price(levels: Any) -> float | None:
    if not levels:
        return None
    first = levels[0]
    if not isinstance(first, Sequence) or isinstance(first, (str, bytes)) or not first:
        return None
    return optional_float(first[0])


def value_or(values: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values:
            return values[key]
    return None


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except Exception:
        return None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str) and value:
        try:
            return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None
