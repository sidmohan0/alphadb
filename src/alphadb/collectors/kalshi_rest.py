"""REST-first Kalshi market-data collector.

The collector is intentionally read-only: it discovers markets and records raw
REST-shaped snapshots, but it has no order-entry dependency.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib import parse, request
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.markets.registry import MarketRegistry, default_market_registry
from alphadb.markets.spec import MarketSpec
from alphadb.state.repository import OperationalStateRepository

KALSHI_REST_SOURCE = "kalshi_rest"
MARKET_SNAPSHOT_SCHEMA = "kalshi.market_snapshot.v1"
ORDERBOOK_SNAPSHOT_SCHEMA = "kalshi.orderbook_snapshot.v1"


class KalshiRestClient(Protocol):
    def list_markets(
        self,
        *,
        series_ticker: str,
        status: str,
        limit: int,
    ) -> Mapping[str, Any]:
        """Return a Kalshi `GET /markets` compatible payload."""

    def get_orderbook(self, market_ticker: str) -> Mapping[str, Any]:
        """Return a Kalshi `GET /markets/{ticker}/orderbook` compatible payload."""


@dataclass(frozen=True)
class CollectorError:
    stage: str
    message: str
    market_ticker: str | None = None

    def as_dict(self) -> dict[str, str]:
        row = {"stage": self.stage, "message": self.message}
        if self.market_ticker is not None:
            row["market_ticker"] = self.market_ticker
        return row


@dataclass(frozen=True)
class StartedCollectorRun:
    collector_run_id: str
    platform_run_id: str


@dataclass(frozen=True)
class CollectorRunSummary:
    collector_run_id: str
    platform_run_id: str
    series: str
    source: str
    status: str
    started_at: datetime
    finished_at: datetime
    markets_discovered: int
    markets_collected: int
    raw_events_written: int
    market_tickers: tuple[str, ...]
    errors: tuple[CollectorError, ...]
    orders_placed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "collector_run_id": self.collector_run_id,
            "platform_run_id": self.platform_run_id,
            "series": self.series,
            "source": self.source,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "markets_discovered": self.markets_discovered,
            "markets_collected": self.markets_collected,
            "raw_events_written": self.raw_events_written,
            "market_tickers": list(self.market_tickers),
            "errors": [error.as_dict() for error in self.errors],
            "orders_placed": self.orders_placed,
        }


class HttpKalshiRestClient:
    """Tiny public market-data client for Kalshi REST endpoints."""

    def __init__(self, base_url: str, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def list_markets(
        self,
        *,
        series_ticker: str,
        status: str,
        limit: int,
    ) -> Mapping[str, Any]:
        return self._get(
            "/markets",
            {
                "series_ticker": series_ticker,
                "status": status,
                "limit": str(limit),
            },
        )

    def get_orderbook(self, market_ticker: str) -> Mapping[str, Any]:
        ticker = parse.quote(market_ticker, safe="")
        return self._get(f"/markets/{ticker}/orderbook")

    def _get(self, path: str, params: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        query = f"?{parse.urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        http_request = request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "alphadb/0.1"},
            method="GET",
        )
        with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"Kalshi response was not a JSON object: {url}")
        return payload


class FixtureKalshiRestClient:
    """Deterministic REST-shaped client for local smoke tests."""

    def __init__(
        self,
        *,
        markets: Sequence[Mapping[str, Any]] | None = None,
        orderbooks: Mapping[str, Mapping[str, Any]] | None = None,
    ):
        self._markets = list(markets) if markets is not None else _default_fixture_markets()
        self._orderbooks = dict(orderbooks) if orderbooks is not None else _default_fixture_orderbooks()
        self.list_market_calls: list[dict[str, Any]] = []
        self.orderbook_calls: list[str] = []

    def list_markets(
        self,
        *,
        series_ticker: str,
        status: str,
        limit: int,
    ) -> Mapping[str, Any]:
        self.list_market_calls.append(
            {"series_ticker": series_ticker, "status": status, "limit": limit}
        )
        markets = [
            market
            for market in self._markets
            if market.get("series_ticker") == series_ticker and market.get("status") == status
        ]
        return {"markets": markets[:limit], "cursor": ""}

    def get_orderbook(self, market_ticker: str) -> Mapping[str, Any]:
        self.orderbook_calls.append(market_ticker)
        try:
            return self._orderbooks[market_ticker]
        except KeyError as exc:
            raise KeyError(f"fixture orderbook not found: {market_ticker}") from exc


class CollectorRunStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def start(
        self,
        *,
        spec: MarketSpec,
        source: str,
        started_at: datetime,
        metadata: Mapping[str, Any],
    ) -> StartedCollectorRun:
        suffix = uuid4().hex[:12]
        platform_run_id = f"run_{suffix}"
        collector_run_id = f"collector_{suffix}"
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into platform_runs (
                        run_id, mode, market_series, status, started_at, metadata
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        platform_run_id,
                        "rest_collector",
                        spec.series,
                        "running",
                        started_at,
                        Jsonb({"spec_version": spec.spec_version, **dict(metadata)}),
                    ),
                )
                cursor.execute(
                    """
                    insert into collector_runs (
                        collector_run_id,
                        platform_run_id,
                        series,
                        source,
                        status,
                        started_at,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        collector_run_id,
                        platform_run_id,
                        spec.series,
                        source,
                        "running",
                        started_at,
                        Jsonb(dict(metadata)),
                    ),
                )
            connection.commit()
        return StartedCollectorRun(
            collector_run_id=collector_run_id,
            platform_run_id=platform_run_id,
        )

    def upsert_market_instance(
        self,
        *,
        spec: MarketSpec,
        market: Mapping[str, Any],
        observed_at: datetime,
    ) -> str:
        market_ticker = str(market["ticker"])
        open_time = parse_kalshi_datetime(market.get("open_time"), observed_at)
        close_time = parse_kalshi_datetime(
            market.get("close_time")
            or market.get("expected_expiration_time")
            or market.get("expiration_time"),
            open_time + timedelta(minutes=spec.horizon_minutes),
        )
        status = str(market.get("status") or "unknown")
        metadata = {
            "event_ticker": market.get("event_ticker"),
            "title": market.get("title"),
            "subtitle": market.get("subtitle"),
            "yes_bid_dollars": market.get("yes_bid_dollars"),
            "yes_ask_dollars": market.get("yes_ask_dollars"),
            "no_bid_dollars": market.get("no_bid_dollars"),
            "no_ask_dollars": market.get("no_ask_dollars"),
            "observed_at": observed_at.isoformat(),
        }

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into market_instances (
                        market_ticker, series, open_time, close_time, status, metadata
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (market_ticker) do update set
                        series = excluded.series,
                        open_time = excluded.open_time,
                        close_time = excluded.close_time,
                        status = excluded.status,
                        metadata = excluded.metadata
                    """,
                    (
                        market_ticker,
                        spec.series,
                        open_time,
                        close_time,
                        status,
                        Jsonb(metadata),
                    ),
                )
            connection.commit()
        return market_ticker

    def finish(
        self,
        *,
        run: StartedCollectorRun,
        status: str,
        finished_at: datetime,
        markets_discovered: int,
        markets_collected: int,
        raw_events_written: int,
        errors: Sequence[CollectorError],
    ) -> None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update collector_runs
                    set
                        status = %s,
                        finished_at = %s,
                        markets_discovered = %s,
                        markets_collected = %s,
                        raw_events_written = %s,
                        errors = %s
                    where collector_run_id = %s
                    """,
                    (
                        status,
                        finished_at,
                        markets_discovered,
                        markets_collected,
                        raw_events_written,
                        Jsonb([error.as_dict() for error in errors]),
                        run.collector_run_id,
                    ),
                )
                cursor.execute(
                    """
                    update platform_runs
                    set status = %s
                    where run_id = %s
                    """,
                    (status, run.platform_run_id),
                )
            connection.commit()

    def recent_runs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        collector_run_id,
                        platform_run_id,
                        series,
                        source,
                        status,
                        started_at,
                        finished_at,
                        markets_discovered,
                        markets_collected,
                        raw_events_written,
                        jsonb_array_length(errors) as errors,
                        errors->0 as latest_error
                    from collector_runs
                    order by started_at desc, collector_run_id desc
                    limit %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]


class RestKxbtc15mCollector:
    def __init__(
        self,
        *,
        database_url: str,
        client: KalshiRestClient,
        registry: MarketRegistry | None = None,
        source_mode: str = "fixture",
    ):
        self.database_url = database_url
        self.client = client
        self.registry = registry or default_market_registry()
        self.source_mode = source_mode
        self.repository = OperationalStateRepository(database_url)
        self.event_log = RawEventLog(database_url)
        self.run_store = CollectorRunStore(database_url)

    def collect(
        self,
        *,
        series: str = "KXBTC15M",
        status: str = "open",
        max_markets: int = 1,
        now: datetime | None = None,
    ) -> CollectorRunSummary:
        if max_markets < 1:
            raise ValueError("max_markets must be at least 1")

        spec = self.registry.get(series)
        self.repository.apply_migrations()
        started_at = now or datetime.now(UTC)
        run = self.run_store.start(
            spec=spec,
            source=KALSHI_REST_SOURCE,
            started_at=started_at,
            metadata={"source_mode": self.source_mode, "requested_status": status},
        )

        errors: list[CollectorError] = []
        market_tickers: list[str] = []
        raw_events_written = 0
        markets_discovered = 0

        try:
            payload = self.client.list_markets(
                series_ticker=spec.discovery_rules.series_ticker,
                status=status,
                limit=max_markets,
            )
            markets = eligible_markets(spec, payload.get("markets", []))
            markets_discovered = len(markets)
        except Exception as exc:
            markets = []
            errors.append(CollectorError(stage="discover_markets", message=str(exc)))

        for market in markets[:max_markets]:
            ticker = str(market.get("ticker"))
            try:
                market_ticker = self.run_store.upsert_market_instance(
                    spec=spec,
                    market=market,
                    observed_at=started_at,
                )
                market_tickers.append(market_ticker)
                market_event = self.event_log.append(
                    run_id=run.platform_run_id,
                    market_ticker=market_ticker,
                    source=KALSHI_REST_SOURCE,
                    source_event_id=f"{run.collector_run_id}:{market_ticker}:market",
                    received_at=started_at,
                    source_timestamp=parse_kalshi_datetime(market.get("updated_time"), started_at),
                    schema_version=MARKET_SNAPSHOT_SCHEMA,
                    payload={
                        "collector_run_id": run.collector_run_id,
                        "source_mode": self.source_mode,
                        "snapshot_type": "market",
                        "market": dict(market),
                    },
                )
                raw_events_written += int(market_event.inserted)

                orderbook_payload = self.client.get_orderbook(market_ticker)
                orderbook_event = self.event_log.append(
                    run_id=run.platform_run_id,
                    market_ticker=market_ticker,
                    source=KALSHI_REST_SOURCE,
                    source_event_id=f"{run.collector_run_id}:{market_ticker}:orderbook",
                    received_at=started_at,
                    schema_version=ORDERBOOK_SNAPSHOT_SCHEMA,
                    payload={
                        "collector_run_id": run.collector_run_id,
                        "source_mode": self.source_mode,
                        "snapshot_type": "orderbook",
                        "market_ticker": market_ticker,
                        "orderbook": dict(orderbook_payload),
                    },
                )
                raw_events_written += int(orderbook_event.inserted)
            except Exception as exc:
                errors.append(
                    CollectorError(
                        stage="collect_market_snapshot",
                        market_ticker=ticker,
                        message=str(exc),
                    )
                )

        finished_at = datetime.now(UTC)
        status_value = "completed" if not errors else "completed_with_errors"
        self.run_store.finish(
            run=run,
            status=status_value,
            finished_at=finished_at,
            markets_discovered=markets_discovered,
            markets_collected=len(market_tickers),
            raw_events_written=raw_events_written,
            errors=errors,
        )

        return CollectorRunSummary(
            collector_run_id=run.collector_run_id,
            platform_run_id=run.platform_run_id,
            series=spec.series,
            source=KALSHI_REST_SOURCE,
            status=status_value,
            started_at=started_at,
            finished_at=finished_at,
            markets_discovered=markets_discovered,
            markets_collected=len(market_tickers),
            raw_events_written=raw_events_written,
            market_tickers=tuple(market_tickers),
            errors=tuple(errors),
        )


def eligible_markets(
    spec: MarketSpec,
    markets: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    prefix = spec.discovery_rules.market_ticker_prefix
    return [market for market in markets if str(market.get("ticker", "")).startswith(prefix)]


def parse_kalshi_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return fallback
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return fallback


def _default_fixture_markets() -> list[Mapping[str, Any]]:
    return [
        {
            "ticker": "KXBTC15M-26MAY312100-00",
            "series_ticker": "KXBTC15M",
            "event_ticker": "KXBTC15M-26MAY312100",
            "status": "open",
            "open_time": "2026-05-31T21:00:00Z",
            "close_time": "2026-05-31T21:15:00Z",
            "updated_time": "2026-05-31T21:12:00Z",
            "title": "Bitcoin above prior 15 minute mark?",
            "payout_threshold": "100.50",
            "yes_bid_dollars": "0.4800",
            "yes_ask_dollars": "0.5200",
            "no_bid_dollars": "0.4700",
            "no_ask_dollars": "0.5300",
        },
        {
            "ticker": "KXBTC15M-26MAY312115-15",
            "series_ticker": "KXBTC15M",
            "event_ticker": "KXBTC15M-26MAY312115",
            "status": "open",
            "open_time": "2026-05-31T21:15:00Z",
            "close_time": "2026-05-31T21:30:00Z",
            "updated_time": "2026-05-31T21:12:00Z",
            "title": "Bitcoin above prior 15 minute mark?",
            "payout_threshold": "101.50",
            "yes_bid_dollars": "0.4900",
            "yes_ask_dollars": "0.5100",
            "no_bid_dollars": "0.4800",
            "no_ask_dollars": "0.5200",
        },
    ]


def _default_fixture_orderbooks() -> dict[str, Mapping[str, Any]]:
    return {
        "KXBTC15M-26MAY312100-00": {
            "orderbook_fp": {
                "yes_dollars": [["0.4800", "14.00"], ["0.4700", "9.00"]],
                "no_dollars": [["0.4700", "11.00"], ["0.4600", "8.00"]],
            }
        },
        "KXBTC15M-26MAY312115-15": {
            "orderbook_fp": {
                "yes_dollars": [["0.4900", "10.00"], ["0.4800", "7.00"]],
                "no_dollars": [["0.4800", "12.00"], ["0.4700", "5.00"]],
            }
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-collect")
    subparsers = parser.add_subparsers(dest="command", required=True)

    smoke_parser = subparsers.add_parser(
        "kxbtc15m-smoke",
        help="Run a bounded, read-only KXBTC15M REST collection smoke",
    )
    smoke_parser.add_argument("--series", default="KXBTC15M")
    smoke_parser.add_argument("--status", default="open")
    smoke_parser.add_argument("--max-markets", type=int, default=1)
    smoke_parser.add_argument(
        "--source",
        choices=("fixture", "kalshi-public"),
        default="fixture",
        help="Use deterministic fixture data or Kalshi public REST market-data endpoints",
    )
    smoke_parser.add_argument("--base-url", default=None)

    status_parser = subparsers.add_parser("status", help="Show recent collector runs")
    status_parser.add_argument("--limit", type=int, default=10)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    repository = OperationalStateRepository(settings.database_url)
    repository.apply_migrations()

    if args.command == "kxbtc15m-smoke":
        client: KalshiRestClient
        if args.source == "fixture":
            client = FixtureKalshiRestClient()
        else:
            client = HttpKalshiRestClient(args.base_url or settings.kalshi_base_url)

        collector = RestKxbtc15mCollector(
            database_url=settings.database_url,
            client=client,
            source_mode=args.source,
        )
        summary = collector.collect(
            series=args.series,
            status=args.status,
            max_markets=args.max_markets,
        )
        print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "status":
        rows = CollectorRunStore(settings.database_url).recent_runs(limit=args.limit)
        print(json.dumps(rows, indent=2, sort_keys=True, default=str))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
