from datetime import UTC, datetime

import psycopg
import pytest

from alphadb.collectors.kalshi_ws import (
    KALSHI_WS_SOURCE,
    KalshiWebSocketCredentials,
    KalshiWebSocketIngestor,
    LiveWebSocketSmokeGuardError,
    MockKalshiWebSocketClient,
    WebSocketEvent,
    assert_live_smoke_enabled,
)
from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.state.repository import OperationalStateRepository


def ws_repository_or_skip() -> OperationalStateRepository:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository


def test_mock_websocket_ingestion_writes_raw_events_without_credentials() -> None:
    repository = ws_repository_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    event = WebSocketEvent(
        channel="orderbook_delta",
        market_ticker=tracer.market_ticker,
        sequence=42,
        received_at=datetime(2026, 5, 31, 21, 45, tzinfo=UTC),
        source_timestamp=datetime(2026, 5, 31, 21, 45, tzinfo=UTC),
        payload={"yes": [["0.5100", "3"]], "no": [["0.4800", "4"]]},
    )

    result = KalshiWebSocketIngestor(repository.database_url).ingest(
        MockKalshiWebSocketClient([event]).receive(),
        run_id=tracer.run_id,
    )
    replayed = list(RawEventLog(repository.database_url).replay_events(run_id=tracer.run_id))

    assert result.source == KALSHI_WS_SOURCE
    assert result.events_seen == 1
    assert result.events_inserted == 1
    assert result.schemas == ("kalshi.ws.orderbook_delta.v1",)
    assert any(row["source"] == "kalshi_ws" for row in replayed)


def test_websocket_and_rest_sources_are_distinguishable_in_counts() -> None:
    repository = ws_repository_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    RawEventLog(repository.database_url).append(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        source="kalshi_rest",
        source_event_id=f"{tracer.market_ticker}:rest-for-ws-counts",
        schema_version="kalshi.orderbook_snapshot.v1",
        payload={"fixture": "rest"},
    )
    KalshiWebSocketIngestor(repository.database_url).ingest(
        [
            WebSocketEvent(
                channel="orderbook_delta",
                market_ticker=tracer.market_ticker,
                sequence=43,
                received_at=datetime(2026, 5, 31, 21, 46, tzinfo=UTC),
                payload={"fixture": "ws"},
            )
        ],
        run_id=tracer.run_id,
    )
    counts = RawEventLog(repository.database_url).counts_by_source_schema()

    assert any(row["source"] == "kalshi_rest" for row in counts)
    assert any(row["source"] == "kalshi_ws" for row in counts)
    assert all("schema_version" in row for row in counts)


def test_websocket_credentials_load_only_from_environment_and_validate_key_path(tmp_path) -> None:
    key_path = tmp_path / "kalshi.key"
    key_path.write_text("private-key", encoding="utf-8")
    settings = settings_from_env(
        {
            "ALPHADB_KALSHI_WS_URL": "wss://example.test/ws",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": str(key_path),
        }
    )

    credentials = KalshiWebSocketCredentials.from_settings(settings)

    assert credentials.api_key_id == "key-id"
    assert credentials.private_key_path == str(key_path)
    assert credentials.websocket_url == "wss://example.test/ws"


def test_live_websocket_smoke_is_explicitly_guarded(tmp_path) -> None:
    key_path = tmp_path / "kalshi.key"
    key_path.write_text("private-key", encoding="utf-8")

    with pytest.raises(LiveWebSocketSmokeGuardError):
        assert_live_smoke_enabled(settings_from_env({}))

    settings = settings_from_env(
        {
            "ALPHADB_ENABLE_LIVE_WS_SMOKE": "1",
            "ALPHADB_KALSHI_WS_URL": "wss://example.test/ws",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": str(key_path),
        }
    )

    credentials = assert_live_smoke_enabled(settings)
    assert credentials.api_key_id == "key-id"
