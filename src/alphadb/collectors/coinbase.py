"""Coinbase BTC-USD external feature adapter for live-data paper runs."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib import parse, request

from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.features.ledger import ensure_utc
from alphadb.state.repository import OperationalStateRepository

COINBASE_SOURCE = "coinbase_exchange"
COINBASE_FEATURE_SCHEMA = "coinbase.btc_usd_features.v1"


class CoinbaseFeatureError(ValueError):
    """Base class for Coinbase feature-normalization failures."""


class MissingCoinbaseDataError(CoinbaseFeatureError):
    """Raised when Coinbase returned no usable candles."""


class StaleCoinbaseDataError(CoinbaseFeatureError):
    """Raised when the latest eligible candle is too old for a decision."""


class CoinbaseNoLookaheadError(CoinbaseFeatureError):
    """Raised when source data is newer than the decision timestamp."""


class CoinbaseClient(Protocol):
    def get_candles(
        self,
        *,
        product_id: str,
        start: datetime,
        end: datetime,
        granularity_seconds: int,
    ) -> Sequence[Sequence[Any]]:
        """Return Coinbase Exchange candle arrays: time, low, high, open, close, volume."""


class HttpCoinbaseClient:
    def __init__(self, base_url: str = "https://api.exchange.coinbase.com", timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_candles(
        self,
        *,
        product_id: str,
        start: datetime,
        end: datetime,
        granularity_seconds: int,
    ) -> Sequence[Sequence[Any]]:
        params = {
            "start": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "end": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "granularity": str(granularity_seconds),
        }
        product = parse.quote(product_id, safe="")
        url = f"{self.base_url}/products/{product}/candles?{parse.urlencode(params)}"
        http_request = request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "alphadb/0.1"},
            method="GET",
        )
        with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise CoinbaseFeatureError("Coinbase candles response was not a list")
        return payload


class FixtureCoinbaseClient:
    def __init__(self, candles: Sequence[Sequence[Any]] | None = None):
        self.candles = list(candles) if candles is not None else default_fixture_candles()
        self.calls: list[dict[str, Any]] = []

    def get_candles(
        self,
        *,
        product_id: str,
        start: datetime,
        end: datetime,
        granularity_seconds: int,
    ) -> Sequence[Sequence[Any]]:
        self.calls.append(
            {
                "product_id": product_id,
                "start": start,
                "end": end,
                "granularity_seconds": granularity_seconds,
            }
        )
        return self.candles


@dataclass(frozen=True)
class CoinbaseFeatureResult:
    product_id: str
    decision_timestamp: datetime
    max_source_event_timestamp: datetime
    source_lag_ms: int
    feature_values: Mapping[str, float]
    raw_event_id: str
    payload_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "max_source_event_timestamp": self.max_source_event_timestamp.isoformat(),
            "source_lag_ms": self.source_lag_ms,
            "feature_values": dict(self.feature_values),
            "raw_event_id": self.raw_event_id,
            "payload_hash": self.payload_hash,
        }


class CoinbaseFeatureAdapter:
    def __init__(
        self,
        *,
        database_url: str,
        client: CoinbaseClient,
        product_id: str = "BTC-USD",
        granularity_seconds: int = 60,
        lookback_minutes: int = 60,
        max_staleness_seconds: int | None = None,
    ):
        self.database_url = database_url
        self.client = client
        self.product_id = product_id
        self.granularity_seconds = granularity_seconds
        self.lookback_minutes = lookback_minutes
        self.max_staleness_seconds = max_staleness_seconds or granularity_seconds * 3
        self.event_log = RawEventLog(database_url)

    def collect_feature_event(
        self,
        *,
        run_id: str,
        market_ticker: str,
        decision_timestamp: datetime,
        received_at: datetime | None = None,
    ) -> CoinbaseFeatureResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        decision_ts = ensure_utc(decision_timestamp)
        start = decision_ts - timedelta(minutes=self.lookback_minutes)
        raw_candles = self.client.get_candles(
            product_id=self.product_id,
            start=start,
            end=decision_ts,
            granularity_seconds=self.granularity_seconds,
        )
        candles = normalize_coinbase_candles(raw_candles)
        eligible = [candle for candle in candles if candle["timestamp"] <= decision_ts]
        if not eligible:
            raise MissingCoinbaseDataError("no Coinbase candles at or before decision timestamp")
        latest = eligible[-1]
        if latest["timestamp"] > decision_ts:
            raise CoinbaseNoLookaheadError("Coinbase candle timestamp is after decision timestamp")
        staleness = (decision_ts - latest["timestamp"]).total_seconds()
        if staleness > self.max_staleness_seconds:
            raise StaleCoinbaseDataError(
                f"latest Coinbase candle is stale by {int(staleness)} seconds"
            )
        features = build_external_price_features(eligible)
        features["external_granularity_seconds"] = float(self.granularity_seconds)
        source_lag_ms = int(staleness * 1000)
        payload = {
            "product_id": self.product_id,
            "granularity_seconds": self.granularity_seconds,
            "data_role": "feature_only",
            "is_label_truth": False,
            "label_truth_source": "kalshi_market_result",
            "decision_timestamp": decision_ts.isoformat(),
            "candles": [serialize_candle(candle) for candle in eligible],
            "feature_values": features,
        }
        event = self.event_log.append(
            run_id=run_id,
            market_ticker=market_ticker,
            source=COINBASE_SOURCE,
            schema_version=COINBASE_FEATURE_SCHEMA,
            payload=payload,
            source_event_id=(
                f"{run_id}:{market_ticker}:{self.product_id}:"
                f"{latest['timestamp'].isoformat()}:coinbase-features"
            ),
            received_at=received_at or decision_ts,
            source_timestamp=latest["timestamp"],
        )
        return CoinbaseFeatureResult(
            product_id=self.product_id,
            decision_timestamp=decision_ts,
            max_source_event_timestamp=latest["timestamp"],
            source_lag_ms=source_lag_ms,
            feature_values=features,
            raw_event_id=event.raw_event_id,
            payload_hash=event.payload_hash,
        )


def normalize_coinbase_candles(raw_candles: Iterable[Sequence[Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in raw_candles:
        values = list(raw)
        if len(values) != 6:
            raise CoinbaseFeatureError(f"expected 6 Coinbase candle values, got {len(values)}")
        ts, low, high, open_, close, volume = values
        try:
            timestamp = datetime.fromtimestamp(int(ts), tz=UTC)
            rows.append(
                {
                    "timestamp": timestamp,
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume),
                }
            )
        except (TypeError, ValueError) as exc:
            raise CoinbaseFeatureError(f"malformed Coinbase candle: {values}") from exc
    deduped = {row["timestamp"]: row for row in rows}
    return [deduped[key] for key in sorted(deduped)]


def build_external_price_features(candles: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    if not candles:
        raise MissingCoinbaseDataError("cannot build features without Coinbase candles")
    latest = candles[-1]
    closes = [float(row["close"]) for row in candles]
    log_returns = [
        math.log(closes[index] / closes[index - 1])
        for index in range(1, len(closes))
        if closes[index - 1] > 0 and closes[index] > 0
    ]
    prev_close = closes[-2] if len(closes) >= 2 else None
    features = {
        "external_granularity_seconds": 60.0,
        "external_open": float(latest["open"]),
        "external_high": float(latest["high"]),
        "external_low": float(latest["low"]),
        "external_close": float(latest["close"]),
        "external_volume": float(latest["volume"]),
        "external_return_1": 0.0
        if prev_close in (None, 0)
        else (float(latest["close"]) / float(prev_close)) - 1.0,
        "external_log_return_1": 0.0 if not log_returns else log_returns[-1],
        "external_close_to_open_return": (float(latest["close"]) / float(latest["open"])) - 1.0,
        "external_range_pct": (float(latest["high"]) - float(latest["low"])) / float(latest["close"]),
        "external_realized_vol_5": sample_std(log_returns[-5:]),
        "external_realized_vol_15": sample_std(log_returns[-15:]),
    }
    features.update(build_coinbase_btc_market_structure_features(candles, log_returns))
    return features


def build_coinbase_btc_market_structure_features(
    candles: Sequence[Mapping[str, Any]],
    log_returns: Sequence[float],
) -> dict[str, float]:
    latest = candles[-1]
    closes = [float(row["close"]) for row in candles]
    close = float(latest["close"])
    open_ = float(latest["open"])
    high = float(latest["high"])
    low = float(latest["low"])
    volume = float(latest["volume"])
    log_return_1 = float(log_returns[-1]) if log_returns else 0.0
    close_to_open = 0.0 if open_ == 0 else (close / open_) - 1.0
    range_pct = 0.0 if close == 0 else (high - low) / close
    vol_5 = sample_std(log_returns[-5:])
    vol_15 = sample_std(log_returns[-15:])
    features = {
        "coinbase_btc_momentum_1m": 0.0 if len(closes) < 2 else (close / closes[-2]) - 1.0,
        "coinbase_btc_log_momentum_1m": log_return_1,
        "coinbase_btc_abs_log_momentum_1m": abs(log_return_1),
        "coinbase_btc_close_to_open_return": close_to_open,
        "coinbase_btc_candle_body_pct": 0.0 if open_ == 0 else (close - open_) / open_,
        "coinbase_btc_realized_range_pct": range_pct,
        "coinbase_btc_realized_volatility_5m": vol_5,
        "coinbase_btc_realized_volatility_15m": vol_15,
        "coinbase_btc_volatility_ratio_15m_5m": vol_15 / max(vol_5, 1e-12),
        "coinbase_btc_candle_shock_5m": abs(log_return_1) / max(vol_5, 1e-12),
        "coinbase_btc_range_shock_5m": range_pct / max(vol_5, 1e-12),
        "coinbase_btc_continuation_pressure": log_return_1 * close_to_open,
        "coinbase_btc_reversal_pressure": -(log_return_1 * close_to_open),
        "coinbase_btc_volume": volume,
        "coinbase_btc_log_volume": math.log1p(max(volume, 0.0)),
    }
    for window in (5, 15):
        if len(closes) > window and closes[-window - 1] > 0:
            features[f"coinbase_btc_momentum_{window}m"] = (close / closes[-window - 1]) - 1.0
        trailing = candles[-window:]
        if trailing:
            high_window = max(float(row["high"]) for row in trailing)
            low_window = min(float(row["low"]) for row in trailing)
            volume_window = sum(float(row["volume"]) for row in trailing)
            features[f"coinbase_btc_realized_range_{window}m_pct"] = (
                0.0 if close == 0 else (high_window - low_window) / close
            )
            features[f"coinbase_btc_volume_{window}m"] = volume_window
    volume_5 = features.get("coinbase_btc_volume_5m")
    volume_15 = features.get("coinbase_btc_volume_15m")
    if volume_5 is not None and volume_15 is not None:
        features["coinbase_btc_volume_ratio_5m_15m"] = volume_5 / max(volume_15, 1e-12)
    return features


def sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def serialize_candle(candle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in candle.items()
    }


def default_fixture_candles() -> list[Sequence[Any]]:
    return [
        [1_780_261_800, 100.0, 101.0, 100.5, 100.8, 1.5],
        [1_780_261_860, 100.1, 101.2, 100.8, 101.0, 1.7],
        [1_780_261_920, 100.4, 101.3, 101.0, 101.2, 1.4],
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-coinbase")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect-features", help="Collect one Coinbase feature event")
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--market-ticker", required=True)
    collect.add_argument("--decision-timestamp", required=True)
    collect.add_argument("--source", choices=("fixture", "coinbase-live"), default="fixture")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    if args.command == "collect-features":
        client: CoinbaseClient = (
            FixtureCoinbaseClient() if args.source == "fixture" else HttpCoinbaseClient()
        )
        result = CoinbaseFeatureAdapter(
            database_url=settings.database_url,
            client=client,
            product_id=settings.coinbase_product_id,
            granularity_seconds=settings.coinbase_granularity_seconds,
            lookback_minutes=settings.coinbase_lookback_minutes,
        ).collect_feature_event(
            run_id=args.run_id,
            market_ticker=args.market_ticker,
            decision_timestamp=datetime.fromisoformat(
                args.decision_timestamp.replace("Z", "+00:00")
            ),
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
