"""Canonical live trade settlement and P&L materialization."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib import parse, request

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import Settings
from alphadb.model_evaluation.metrics import taker_fee
from alphadb.state.repository import OperationalStateRepository


SETTLEMENT_SOURCE_KALSHI_PUBLIC_MARKET_API = "kalshi_public_market_api"
LIVE_TRADE_RECONCILIATION_SCHEMA = "alphadb_live_trade_reconciliation.v1"
LIVE_TRADE_RECONCILIATION_SUMMARY_SCHEMA = "alphadb_live_trade_reconciliation_summary.v1"

SETTLED_STATUSES = {"settled_win", "settled_loss", "settled_flat"}
UNSETTLED_FILLED_STATUSES = {"open", "settlement_unavailable", "lookup_failed"}


class LiveSettlementError(RuntimeError):
    """Raised when live settlement reconciliation cannot proceed safely."""


@dataclass(frozen=True)
class MarketResultObservation:
    market_ticker: str
    status: str | None
    result: str | None
    source: str | None = SETTLEMENT_SOURCE_KALSHI_PUBLIC_MARKET_API
    observed_at: datetime | None = None
    metadata: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "market_ticker": self.market_ticker,
            "status": self.status,
            "result": self.result,
            "source": self.source,
            "observed_at": _iso(self.observed_at),
            "metadata": dict(self.metadata or {}),
        }


class MarketResultClient(Protocol):
    def get_market_result(
        self,
        *,
        ticker: str,
        settings: Settings,
        observed_at: datetime,
    ) -> MarketResultObservation:
        """Return a public market-result observation for one Kalshi ticker."""


class KalshiPublicMarketResultClient:
    """Small public Kalshi market-result lookup client."""

    def get_market_result(
        self,
        *,
        ticker: str,
        settings: Settings,
        observed_at: datetime,
    ) -> MarketResultObservation:
        if not ticker:
            return MarketResultObservation(
                market_ticker=ticker,
                status=None,
                result=None,
                observed_at=observed_at,
                metadata={"error": "missing_ticker"},
            )
        url = f"{settings.kalshi_base_url.rstrip('/')}/markets/{parse.quote(ticker, safe='')}"
        try:
            http_request = request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "alphadb/0.1"},
                method="GET",
            )
            with request.urlopen(http_request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            market = _mapping(payload.get("market")) if isinstance(payload, Mapping) else {}
            result = _lower_text(market.get("result"))
            return MarketResultObservation(
                market_ticker=ticker,
                status=_text(market.get("status")),
                result=result if result in {"yes", "no"} else None,
                observed_at=observed_at,
                metadata={"http_status": getattr(response, "status", None)},
            )
        except Exception as exc:
            return MarketResultObservation(
                market_ticker=ticker,
                status="unknown",
                result=None,
                observed_at=observed_at,
                metadata={"error": f"{type(exc).__name__}: {exc}"},
            )


def reconcile_live_order_attempt(
    attempt: Mapping[str, Any],
    *,
    market_result: MarketResultObservation | Mapping[str, Any] | None,
    reconciled_at: datetime,
    taker_fee_multiplier: float = 0.07,
) -> dict[str, Any]:
    """Build one canonical reconciliation row from attempt and market evidence."""

    request_payload = _mapping(attempt.get("request_payload"))
    response_payload = _mapping(attempt.get("response_payload"))
    market_observation = _market_result_observation(
        market_result,
        ticker=_text(attempt.get("market_ticker")) or _text(request_payload.get("ticker")) or "",
    )

    filled_contracts, fill_source = _filled_contracts(attempt, response_payload)
    side, side_source = _selected_side(attempt, request_payload)
    price, price_source = _selected_price(attempt, request_payload, side=side)
    cost, cost_source = _cost_dollars(
        response_payload,
        filled_contracts=filled_contracts,
        price=price,
    )
    fees, fees_source = _fees_dollars(
        response_payload,
        filled_contracts=filled_contracts,
        price=price,
        taker_fee_multiplier=taker_fee_multiplier,
    )
    ticker = (
        _text(attempt.get("market_ticker"))
        or _text(request_payload.get("ticker"))
        or market_observation.market_ticker
    )
    result = _lower_text(market_observation.result)
    lookup_error = _lookup_error(market_observation)

    if filled_contracts <= 0:
        settlement_status = "no_fill"
        payout = 0.0
        net_pnl = 0.0
        unsettled_exposure = 0.0
    elif lookup_error:
        settlement_status = "lookup_failed"
        payout = 0.0
        net_pnl = 0.0
        unsettled_exposure = cost + fees
    elif result in {"yes", "no"} and side in {"yes", "no"}:
        payout = filled_contracts if result == side else 0.0
        net_pnl = payout - cost - fees
        unsettled_exposure = 0.0
        if abs(net_pnl) < 0.0000005:
            settlement_status = "settled_flat"
        elif net_pnl > 0:
            settlement_status = "settled_win"
        else:
            settlement_status = "settled_loss"
    elif _lower_text(market_observation.status) in {"finalized", "settled", "closed"}:
        settlement_status = "settlement_unavailable"
        payout = 0.0
        net_pnl = 0.0
        unsettled_exposure = cost + fees
    else:
        settlement_status = "open"
        payout = 0.0
        net_pnl = 0.0
        unsettled_exposure = cost + fees

    metadata = {
        "schema_version": LIVE_TRADE_RECONCILIATION_SCHEMA,
        "attempt_status": _text(attempt.get("status")),
        "exchange_status": _text(attempt.get("exchange_status")),
        "fill_source": fill_source,
        "side_source": side_source,
        "price_source": price_source,
        "cost_source": cost_source,
        "fees_source": fees_source,
        "fallbacks": [
            source
            for source in (cost_source, fees_source)
            if source.startswith("fallback_")
        ],
        "market_result_observation": market_observation.as_dict(),
    }
    if lookup_error:
        metadata["lookup_error"] = lookup_error

    return {
        "live_order_attempt_id": str(attempt.get("live_order_attempt_id") or ""),
        "strategy": _text(attempt.get("strategy")) or "unknown",
        "run_id": _run_id(attempt, request_payload, response_payload),
        "live_risk_day": _date_or_none(attempt.get("live_risk_day")),
        "market_ticker": ticker,
        "side": side,
        "filled_contracts": _round(filled_contracts),
        "cost_dollars": _round(cost),
        "fees_dollars": _round(fees),
        "market_status": market_observation.status,
        "market_result": result,
        "settlement_status": settlement_status,
        "payout_dollars": _round(payout),
        "net_pnl_dollars": _round(net_pnl),
        "unsettled_exposure_dollars": _round(unsettled_exposure),
        "decision_source": _decision_source(attempt, request_payload, response_payload),
        "settlement_source": market_observation.source if market_observation.source else None,
        "settlement_observed_at": market_observation.observed_at,
        "reconciled_at": reconciled_at,
        "metadata": metadata,
    }


class LiveTradeReconciliationRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def candidate_attempts(
        self,
        *,
        strategy: str,
        limit: int = 500,
        market_ticker: str | None = None,
        live_risk_day: date | None = None,
    ) -> list[dict[str, Any]]:
        OperationalStateRepository(self.database_url).apply_migrations()
        predicates = ["strategy = %s"]
        params: list[Any] = [strategy]
        if market_ticker:
            predicates.append("market_ticker = %s")
            params.append(market_ticker)
        if live_risk_day:
            predicates.append("live_risk_day = %s")
            params.append(live_risk_day)
        params.append(limit)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select *
                    from live_order_attempts
                    where {" and ".join(predicates)}
                    order by submitted_at desc nulls last, created_at desc, live_order_attempt_id desc
                    limit %s
                    """,
                    params,
                )
                return [_json_ready(row) for row in cursor.fetchall()]

    def upsert(self, row: Mapping[str, Any]) -> dict[str, Any]:
        OperationalStateRepository(self.database_url).apply_migrations()
        if not row.get("live_order_attempt_id"):
            raise LiveSettlementError("reconciliation row needs live_order_attempt_id")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into live_trade_reconciliations (
                        live_order_attempt_id,
                        strategy,
                        run_id,
                        live_risk_day,
                        market_ticker,
                        side,
                        filled_contracts,
                        cost_dollars,
                        fees_dollars,
                        market_status,
                        market_result,
                        settlement_status,
                        payout_dollars,
                        net_pnl_dollars,
                        unsettled_exposure_dollars,
                        decision_source,
                        settlement_source,
                        settlement_observed_at,
                        reconciled_at,
                        metadata,
                        updated_at
                    )
                    values (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, now()
                    )
                    on conflict (live_order_attempt_id) do update
                    set strategy = excluded.strategy,
                        run_id = excluded.run_id,
                        live_risk_day = excluded.live_risk_day,
                        market_ticker = excluded.market_ticker,
                        side = excluded.side,
                        filled_contracts = excluded.filled_contracts,
                        cost_dollars = excluded.cost_dollars,
                        fees_dollars = excluded.fees_dollars,
                        market_status = excluded.market_status,
                        market_result = excluded.market_result,
                        settlement_status = excluded.settlement_status,
                        payout_dollars = excluded.payout_dollars,
                        net_pnl_dollars = excluded.net_pnl_dollars,
                        unsettled_exposure_dollars = excluded.unsettled_exposure_dollars,
                        decision_source = excluded.decision_source,
                        settlement_source = excluded.settlement_source,
                        settlement_observed_at = excluded.settlement_observed_at,
                        reconciled_at = excluded.reconciled_at,
                        metadata = excluded.metadata,
                        updated_at = now()
                    returning *
                    """,
                    (
                        row.get("live_order_attempt_id"),
                        row.get("strategy"),
                        row.get("run_id"),
                        row.get("live_risk_day"),
                        row.get("market_ticker"),
                        row.get("side"),
                        row.get("filled_contracts"),
                        row.get("cost_dollars"),
                        row.get("fees_dollars"),
                        row.get("market_status"),
                        row.get("market_result"),
                        row.get("settlement_status"),
                        row.get("payout_dollars"),
                        row.get("net_pnl_dollars"),
                        row.get("unsettled_exposure_dollars"),
                        row.get("decision_source"),
                        row.get("settlement_source"),
                        row.get("settlement_observed_at"),
                        row.get("reconciled_at"),
                        Jsonb(dict(row.get("metadata") or {})),
                    ),
                )
                saved = cursor.fetchone()
            connection.commit()
        if saved is None:
            raise LiveSettlementError("live reconciliation upsert returned no row")
        return _json_ready(saved)

    def recent_rows(
        self,
        *,
        strategy: str,
        limit: int = 500,
        market_series: str | None = None,
    ) -> list[dict[str, Any]]:
        OperationalStateRepository(self.database_url).apply_migrations()
        predicates = ["strategy = %s"]
        params: list[Any] = [strategy]
        if market_series:
            predicates.append("(market_ticker = %s or market_ticker like %s)")
            params.extend([market_series, f"{market_series}-%"])
        params.append(limit)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select *
                    from live_trade_reconciliations
                    where {" and ".join(predicates)}
                    order by reconciled_at desc, live_order_attempt_id desc
                    limit %s
                    """,
                    params,
                )
                return [_json_ready(row) for row in cursor.fetchall()]


def reconcile_live_settlements(
    *,
    database_url: str,
    settings: Settings,
    strategy: str,
    market_client: MarketResultClient | None = None,
    limit: int = 500,
    market_ticker: str | None = None,
    live_risk_day: date | None = None,
    reconciled_at: datetime | None = None,
) -> dict[str, Any]:
    observed_at = reconciled_at or datetime.now(UTC)
    repository = LiveTradeReconciliationRepository(database_url)
    client = market_client or KalshiPublicMarketResultClient()
    attempts = repository.candidate_attempts(
        strategy=strategy,
        limit=limit,
        market_ticker=market_ticker,
        live_risk_day=live_risk_day,
    )
    market_cache: dict[str, MarketResultObservation] = {}
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        response_payload = _mapping(attempt.get("response_payload"))
        filled_contracts, _source = _filled_contracts(attempt, response_payload)
        ticker = _text(attempt.get("market_ticker")) or _text(
            _mapping(attempt.get("request_payload")).get("ticker")
        ) or ""
        market_result: MarketResultObservation | None = None
        if filled_contracts > 0:
            if ticker not in market_cache:
                market_cache[ticker] = client.get_market_result(
                    ticker=ticker,
                    settings=settings,
                    observed_at=observed_at,
                )
            market_result = market_cache[ticker]
        row = reconcile_live_order_attempt(
            attempt,
            market_result=market_result,
            reconciled_at=observed_at,
        )
        rows.append(repository.upsert(row))
    summary = summarize_live_trade_reconciliations(rows, generated_at=observed_at)
    summary["lookup_count"] = len(market_cache)
    return summary


def summarize_live_trade_reconciliations(
    rows: Sequence[Mapping[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    normalized = [dict(row) for row in rows]
    filled = [row for row in normalized if _float(row.get("filled_contracts")) > 0]
    settled = [row for row in filled if _text(row.get("settlement_status")) in SETTLED_STATUSES]
    unsettled = [
        row
        for row in filled
        if _text(row.get("settlement_status")) in UNSETTLED_FILLED_STATUSES
    ]
    wins = [row for row in settled if _text(row.get("settlement_status")) == "settled_win"]
    losses = [row for row in settled if _text(row.get("settlement_status")) == "settled_loss"]
    counts = Counter(_text(row.get("settlement_status")) or "unknown" for row in normalized)
    return {
        "schema_version": LIVE_TRADE_RECONCILIATION_SUMMARY_SCHEMA,
        "generated_at": _iso(generated_at or datetime.now(UTC)),
        "counts": dict(sorted(counts.items())),
        "pnl": {
            "realized_pnl_dollars": _round(
                sum(_float(row.get("net_pnl_dollars")) for row in settled)
            ),
            "net_pnl_dollars": _round(
                sum(_float(row.get("net_pnl_dollars")) for row in settled)
            ),
            "gross_cost_dollars": _round(
                sum(_float(row.get("cost_dollars")) for row in filled)
            ),
            "fees_dollars": _round(sum(_float(row.get("fees_dollars")) for row in filled)),
            "payout_dollars": _round(
                sum(_float(row.get("payout_dollars")) for row in settled)
            ),
            "unsettled_exposure_dollars": _round(
                sum(_float(row.get("unsettled_exposure_dollars")) for row in unsettled)
            ),
            "filled_contracts": _round(
                sum(_float(row.get("filled_contracts")) for row in filled)
            ),
            "settled_trade_count": len(settled),
            "open_trade_count": len(unsettled),
            "no_fill_count": counts.get("no_fill", 0),
            "lookup_failed_count": counts.get("lookup_failed", 0),
            "win_rate": _round(len(wins) / len(settled)) if settled else None,
            "loss_count": len(losses),
        },
        "settlement": {
            "state": _live_settlement_state(normalized),
            "settled_rows": len(settled),
            "unsettled_rows": len(unsettled),
            "default_reporting": "canonical_live_trade_reconciliations",
        },
        "rows": normalized,
    }


def _live_settlement_state(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "unavailable"
    filled = [row for row in rows if _float(row.get("filled_contracts")) > 0]
    if not filled:
        return "complete"
    statuses = {_text(row.get("settlement_status")) for row in filled}
    if statuses <= SETTLED_STATUSES:
        return "complete"
    if statuses & SETTLED_STATUSES:
        return "partial"
    return "unresolved"


def _market_result_observation(
    market_result: MarketResultObservation | Mapping[str, Any] | None,
    *,
    ticker: str,
) -> MarketResultObservation:
    if isinstance(market_result, MarketResultObservation):
        return market_result
    if isinstance(market_result, Mapping):
        metadata = _mapping(market_result.get("metadata"))
        return MarketResultObservation(
            market_ticker=_text(market_result.get("market_ticker")) or ticker,
            status=_text(market_result.get("status")),
            result=_lower_text(market_result.get("result")),
            source=_text(market_result.get("source")) or SETTLEMENT_SOURCE_KALSHI_PUBLIC_MARKET_API,
            observed_at=_datetime(market_result.get("observed_at")),
            metadata=metadata,
        )
    return MarketResultObservation(
        market_ticker=ticker,
        status=None,
        result=None,
        source=None,
        observed_at=None,
        metadata={},
    )


def _filled_contracts(
    attempt: Mapping[str, Any],
    response_payload: Mapping[str, Any],
) -> tuple[float, str]:
    value = _float_or_none(attempt.get("fill_count"))
    if value is not None:
        return max(0.0, value), "live_order_attempt.fill_count"
    value = _numeric_response_value(
        response_payload,
        ("fill_count", "fill_count_fp", "filled_quantity"),
    )
    if value is not None:
        return max(0.0, value), "response_payload.fill_count"
    return 0.0, "missing_fill_count"


def _selected_side(
    attempt: Mapping[str, Any],
    request_payload: Mapping[str, Any],
) -> tuple[str, str]:
    side = _text(attempt.get("intended_side"))
    side = _lower_text(side)
    if side in {"yes", "no"}:
        return side, "live_order_attempt.intended_side"
    request_side = _lower_text(request_payload.get("side"))
    if request_side == "bid":
        return "yes", "request_payload.side"
    if request_side == "ask":
        return "no", "request_payload.side"
    return "", "missing_side"


def _selected_price(
    attempt: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    *,
    side: str,
) -> tuple[float, str]:
    value = _float_or_none(attempt.get("intended_price_dollars"))
    if value is not None:
        return max(0.0, value), "live_order_attempt.intended_price_dollars"
    request_price = _float_or_none(request_payload.get("price"))
    request_side = _lower_text(request_payload.get("side"))
    if request_price is not None:
        if side == "no" or request_side == "ask":
            return max(0.0, 1.0 - request_price), "fallback_request_payload.price_complement"
        return max(0.0, request_price), "fallback_request_payload.price"
    return 0.0, "missing_price"


def _cost_dollars(
    response_payload: Mapping[str, Any],
    *,
    filled_contracts: float,
    price: float,
) -> tuple[float, str]:
    actual = _numeric_response_value(
        response_payload,
        (
            "taker_fill_cost_dollars",
            "maker_fill_cost_dollars",
            "fill_cost_dollars",
            "filled_cost_dollars",
            "cost_dollars",
        ),
    )
    if actual is not None:
        return max(0.0, actual), "response_payload.actual_cost"
    value = max(0.0, price * filled_contracts)
    return value, "fallback_intended_price_times_fill"


def _fees_dollars(
    response_payload: Mapping[str, Any],
    *,
    filled_contracts: float,
    price: float,
    taker_fee_multiplier: float,
) -> tuple[float, str]:
    actual = _numeric_response_value(
        response_payload,
        (
            "taker_fees_dollars",
            "maker_fees_dollars",
            "fees_dollars",
            "fee_dollars",
        ),
    )
    if actual is not None:
        return max(0.0, actual), "response_payload.actual_fees"
    value = max(0.0, taker_fee(price, taker_fee_multiplier) * filled_contracts)
    return value, "fallback_taker_fee_assumption"


def _numeric_response_value(payload: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    order = _mapping(payload.get("order"))
    for source in (payload, order):
        for key in keys:
            value = _float_or_none(source.get(key))
            if value is not None:
                return value
    return None


def _decision_source(
    attempt: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
) -> str | None:
    for source in (attempt, request_payload, _mapping(request_payload.get("metadata")), response_payload):
        value = _text(source.get("decision_source")) or _text(source.get("market_context_source"))
        if value:
            return value
    return None


def _run_id(
    attempt: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
) -> str | None:
    for source in (attempt, request_payload, _mapping(request_payload.get("metadata")), response_payload):
        value = _text(source.get("run_id"))
        if value:
            return value
    return None


def _lookup_error(observation: MarketResultObservation) -> str | None:
    metadata = dict(observation.metadata or {})
    return _text(metadata.get("error"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _lower_text(value: Any) -> str | None:
    text = _text(value)
    return text.lower() if text else None


def _float(value: Any) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 0.0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | int | Decimal) -> float:
    return round(float(value), 6)


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _date_or_none(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return None


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _json_ready(row: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            output[key] = value.isoformat()
        elif isinstance(value, date) and not isinstance(value, datetime):
            output[key] = value.isoformat()
        elif isinstance(value, Decimal):
            output[key] = float(value)
        else:
            output[key] = value
    return output
