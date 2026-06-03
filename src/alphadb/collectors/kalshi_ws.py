"""Authenticated Kalshi WebSocket ingestion readiness.

Normal tests and local smoke paths use mocked WebSocket events. Live smoke needs
explicit environment configuration and does not run by default.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alphadb.config import Settings, settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.state.repository import OperationalStateRepository

KALSHI_WS_SOURCE = "kalshi_ws"
ORDERBOOK_DELTA_SCHEMA = "kalshi.ws.orderbook_delta.v1"
TRADE_SCHEMA = "kalshi.ws.trade.v1"


class LiveWebSocketSmokeGuardError(RuntimeError):
    """Raised when live WebSocket smoke is not explicitly enabled."""


@dataclass(frozen=True)
class KalshiWebSocketCredentials:
    api_key_id: str
    private_key_path: str
    websocket_url: str

    @classmethod
    def from_settings(cls, settings: Settings) -> KalshiWebSocketCredentials:
        missing = []
        if not settings.kalshi_api_key_id:
            missing.append("KALSHI_API_KEY_ID")
        if not settings.kalshi_private_key_path:
            missing.append("KALSHI_PRIVATE_KEY_PATH")
        if not settings.kalshi_ws_url:
            missing.append("ALPHADB_KALSHI_WS_URL")
        if missing:
            raise ValueError(f"missing WebSocket credential settings: {', '.join(missing)}")
        private_key_path = Path(settings.kalshi_private_key_path)
        if not private_key_path.exists():
            raise ValueError(f"KALSHI_PRIVATE_KEY_PATH does not exist: {private_key_path}")
        return cls(
            api_key_id=settings.kalshi_api_key_id,
            private_key_path=str(private_key_path),
            websocket_url=settings.kalshi_ws_url,
        )


@dataclass(frozen=True)
class WebSocketEvent:
    channel: str
    market_ticker: str
    sequence: int
    payload: Mapping[str, Any]
    received_at: datetime
    source_timestamp: datetime | None = None

    @property
    def schema_version(self) -> str:
        if self.channel == "orderbook_delta":
            return ORDERBOOK_DELTA_SCHEMA
        if self.channel == "trade":
            return TRADE_SCHEMA
        return f"kalshi.ws.{self.channel}.v1"

    @property
    def source_event_id(self) -> str:
        return f"{self.channel}:{self.market_ticker}:{self.sequence}"


@dataclass(frozen=True)
class WebSocketIngestResult:
    source: str
    events_seen: int
    events_inserted: int
    schemas: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "events_seen": self.events_seen,
            "events_inserted": self.events_inserted,
            "schemas": list(self.schemas),
        }


class KalshiWebSocketIngestor:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.event_log = RawEventLog(database_url)

    def ingest(
        self,
        events: Iterable[WebSocketEvent],
        *,
        run_id: str | None = None,
    ) -> WebSocketIngestResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        seen = 0
        inserted = 0
        schemas: set[str] = set()
        for event in events:
            seen += 1
            schemas.add(event.schema_version)
            record = self.event_log.append(
                run_id=run_id,
                market_ticker=event.market_ticker,
                source=KALSHI_WS_SOURCE,
                source_event_id=event.source_event_id,
                received_at=event.received_at,
                source_timestamp=event.source_timestamp,
                schema_version=event.schema_version,
                payload={
                    "channel": event.channel,
                    "market_ticker": event.market_ticker,
                    "sequence": event.sequence,
                    "payload": dict(event.payload),
                },
            )
            inserted += int(record.inserted)
        return WebSocketIngestResult(
            source=KALSHI_WS_SOURCE,
            events_seen=seen,
            events_inserted=inserted,
            schemas=tuple(sorted(schemas)),
        )


class MockKalshiWebSocketClient:
    def __init__(self, events: Sequence[WebSocketEvent]):
        self.events = tuple(events)

    def receive(self) -> Iterable[WebSocketEvent]:
        return self.events


def default_mock_event(market_ticker: str) -> WebSocketEvent:
    return WebSocketEvent(
        channel="orderbook_delta",
        market_ticker=market_ticker,
        sequence=1,
        received_at=datetime.now(UTC),
        source_timestamp=datetime.now(UTC),
        payload={
            "yes": [["0.5100", "3"]],
            "no": [["0.4800", "4"]],
        },
    )


def assert_live_smoke_enabled(settings: Settings) -> KalshiWebSocketCredentials:
    if not settings.enable_live_ws_smoke:
        raise LiveWebSocketSmokeGuardError(
            "live WebSocket smoke requires ALPHADB_ENABLE_LIVE_WS_SMOKE=1"
        )
    return KalshiWebSocketCredentials.from_settings(settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-ws")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mock_parser = subparsers.add_parser("mock-smoke", help="Ingest deterministic mocked WS event")
    mock_parser.add_argument("--market-ticker", required=True)
    mock_parser.add_argument("--run-id", default=None)

    subparsers.add_parser("live-smoke", help="Validate live WS smoke configuration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()

    if args.command == "mock-smoke":
        client = MockKalshiWebSocketClient([default_mock_event(args.market_ticker)])
        result = KalshiWebSocketIngestor(settings.database_url).ingest(
            client.receive(),
            run_id=args.run_id,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "live-smoke":
        credentials = assert_live_smoke_enabled(settings)
        print(
            json.dumps(
                {
                    "status": "ready",
                    "websocket_url": credentials.websocket_url,
                    "api_key_id_present": bool(credentials.api_key_id),
                    "private_key_path": credentials.private_key_path,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
