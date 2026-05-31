"""KXBTC15M handled-market scheduler."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from alphadb.markets.spec import MarketSpec
from alphadb.strategy.state import StrategyMarketOutcome, StrategyRunRepository, fresh_outcome


@dataclass(frozen=True)
class MarketCandidate:
    market_ticker: str
    open_time: datetime
    close_time: datetime
    status: str = "open"
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SchedulerScanResult:
    run_id: str
    scanned: int
    waiting: int
    handled: int
    skipped: int
    errored: int
    duplicate_prevented: int
    outcomes: tuple[StrategyMarketOutcome, ...]

    def as_counts(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "waiting": self.waiting,
            "handled": self.handled,
            "skipped": self.skipped,
            "errored": self.errored,
            "duplicate_prevented": self.duplicate_prevented,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            **self.as_counts(),
            "outcomes": [outcome.as_dict() for outcome in self.outcomes],
        }


MarketHandler = Callable[[MarketCandidate, datetime], StrategyMarketOutcome]


class Kxbtc15mHandledMarketScheduler:
    def __init__(self, *, database_url: str, spec: MarketSpec):
        self.database_url = database_url
        self.spec = spec
        self.repository = StrategyRunRepository(database_url)

    def scan(
        self,
        *,
        run_id: str,
        markets: Sequence[MarketCandidate],
        now: datetime,
        handler: MarketHandler,
        keep_run_open: bool = False,
    ) -> SchedulerScanResult:
        now = ensure_utc(now)
        waiting = handled = skipped = errored = duplicate_prevented = 0
        outcomes: list[StrategyMarketOutcome] = []

        for market in markets:
            decision_ts = decision_timestamp_for_market(self.spec, market)
            if now < decision_ts:
                waiting += 1
                continue
            if now > latest_allowed_decision_time(self.spec, market):
                outcome = self.repository.record_outcome(
                    fresh_outcome(
                        run_id=run_id,
                        market_ticker=market.market_ticker,
                        decision_timestamp=now,
                        status="skipped",
                        reason="missed_decision_window",
                        metadata={"scheduler": "kxbtc15m.v1"},
                    )
                )
                if outcome.inserted:
                    skipped += 1
                else:
                    duplicate_prevented += 1
                outcomes.append(outcome)
                continue
            try:
                outcome = self.repository.record_outcome(handler(market, now))
            except Exception as exc:
                outcome = self.repository.record_outcome(
                    fresh_outcome(
                        run_id=run_id,
                        market_ticker=market.market_ticker,
                        decision_timestamp=now,
                        status="error",
                        reason="retryable_handler_error",
                        metadata={
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "retryable": True,
                        },
                    )
                )
            if not outcome.inserted:
                duplicate_prevented += 1
            elif outcome.status == "handled":
                handled += 1
            elif outcome.status == "skipped":
                skipped += 1
            elif outcome.status == "error":
                errored += 1
            outcomes.append(outcome)

        result = SchedulerScanResult(
            run_id=run_id,
            scanned=len(markets),
            waiting=waiting,
            handled=handled,
            skipped=skipped,
            errored=errored,
            duplicate_prevented=duplicate_prevented,
            outcomes=tuple(outcomes),
        )
        self.repository.finish_run(
            run_id=run_id,
            status="running" if keep_run_open or waiting else "completed",
            metadata_patch={"latest_counts": result.as_counts()},
        )
        return result

    def discover_open_markets(self, *, limit: int = 20) -> list[MarketCandidate]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select market_ticker, open_time, close_time, status, metadata
                    from market_instances
                    where series = %s and status = 'open'
                    order by open_time asc
                    limit %s
                    """,
                    (self.spec.series, limit),
                )
                rows = cursor.fetchall()
        return [
            MarketCandidate(
                market_ticker=str(row["market_ticker"]),
                open_time=ensure_utc(row["open_time"]),
                close_time=ensure_utc(row["close_time"]),
                status=str(row["status"]),
                metadata=dict(row["metadata"]),
            )
            for row in rows
        ]


def decision_timestamp_for_market(spec: MarketSpec, market: MarketCandidate) -> datetime:
    return ensure_utc(market.open_time) + timedelta(minutes=spec.trading_cutoffs.decision_minute_offset)


def latest_allowed_decision_time(spec: MarketSpec, market: MarketCandidate) -> datetime:
    return ensure_utc(market.close_time) - timedelta(seconds=spec.trading_cutoffs.settlement_buffer_seconds)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
