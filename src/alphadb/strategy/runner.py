"""Live-data paper strategy runner for KXBTC15M."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from alphadb.artifacts import (
    ArtifactLoadError,
    PinnedModelPolicy,
    load_pinned_model_policy_from_settings,
    register_loaded_model,
)
from alphadb.collectors.coinbase import CoinbaseClient, CoinbaseFeatureAdapter, FixtureCoinbaseClient
from alphadb.collectors.kalshi_rest import (
    FixtureKalshiRestClient,
    KalshiRestClient,
    CollectorRunStore,
    MARKET_SNAPSHOT_SCHEMA,
    ORDERBOOK_SNAPSHOT_SCHEMA,
)
from alphadb.config import settings_from_env
from alphadb.decision_engine.engine import (
    DecisionEngine,
    DecisionRepository,
    build_decision_input,
)
from alphadb.events.log import RawEventLog
from alphadb.features.current_mvp import CurrentMvpFeatureRowBuilder, MissingCurrentMvpFeatureError
from alphadb.features.ledger import MissingFeatureEventsError, NoLookaheadViolationError
from alphadb.markets.registry import default_market_registry
from alphadb.paper.ioc import PaperIocExecutor, PaperLiquidity
from alphadb.risk.gate import RiskDecisionRepository, RiskGate, RiskPolicy, RiskState
from alphadb.runtime import RuntimeMode, evaluate_runtime_guard, settings_with_overrides
from alphadb.strategy.scheduler import Kxbtc15mHandledMarketScheduler, MarketCandidate
from alphadb.strategy.state import StrategyMarketOutcome, StrategyRunRepository, fresh_outcome


@dataclass(frozen=True)
class LiveDataPaperCycleResult:
    run_id: str
    market_ticker: str | None
    outcome: StrategyMarketOutcome | None
    counts: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "market_ticker": self.market_ticker,
            "outcome": None if self.outcome is None else self.outcome.as_dict(),
            "counts": dict(self.counts),
        }


class LiveDataPaperRunner:
    def __init__(
        self,
        *,
        database_url: str,
        policy: PinnedModelPolicy,
        model_id: str,
        kalshi_client: KalshiRestClient | None = None,
        coinbase_client: CoinbaseClient | None = None,
    ):
        self.database_url = database_url
        self.policy = policy
        self.model_id = model_id
        self.kalshi_client = kalshi_client or FixtureKalshiRestClient()
        self.coinbase_client = coinbase_client or FixtureCoinbaseClient()
        self.spec = default_market_registry().get("KXBTC15M")
        self.event_log = RawEventLog(database_url)
        self.collector_store = CollectorRunStore(database_url)
        self.strategy_store = StrategyRunRepository(database_url)

    def run_one_cycle(
        self,
        *,
        run_id: str | None = None,
        now: datetime | None = None,
        max_markets: int = 1,
        daily_realized_pnl_dollars: float = 0.0,
    ) -> LiveDataPaperCycleResult:
        now = ensure_utc(now or datetime.now(UTC))
        guard = evaluate_runtime_guard(
            settings_with_overrides(settings_from_env(), {"runtime_mode": RuntimeMode.PAPER.value})
        )
        if guard.can_submit_live_orders:
            raise RuntimeError("paper runner guard unexpectedly allows live orders")
        if run_id is None:
            run = self.strategy_store.start_run(
                market_series=self.spec.series,
                runtime_mode=RuntimeMode.PAPER,
                started_at=now,
                metadata={
                    "model_artifact_sha256": self.policy.model_artifact_sha256,
                    "feature_schema_sha256": self.policy.feature_schema_sha256,
                },
            )
            run_id = run.run_id

        markets = self._collect_fixture_like_inputs(run_id=run_id, now=now, max_markets=max_markets)
        scheduler = Kxbtc15mHandledMarketScheduler(database_url=self.database_url, spec=self.spec)

        def handler(market: MarketCandidate, decision_timestamp: datetime) -> StrategyMarketOutcome:
            return self._handle_market(
                run_id=run_id,
                market=market,
                decision_timestamp=decision_timestamp,
                daily_realized_pnl_dollars=daily_realized_pnl_dollars,
            )

        scan = scheduler.scan(run_id=run_id, markets=markets, now=now, handler=handler)
        return LiveDataPaperCycleResult(
            run_id=run_id,
            market_ticker=markets[0].market_ticker if markets else None,
            outcome=scan.outcomes[0] if scan.outcomes else None,
            counts={**scan.as_counts(), **self.strategy_store.counts(run_id=run_id)},
        )

    def _collect_fixture_like_inputs(
        self,
        *,
        run_id: str,
        now: datetime,
        max_markets: int,
    ) -> list[MarketCandidate]:
        payload = self.kalshi_client.list_markets(
            series_ticker=self.spec.series,
            status="open",
            limit=max_markets,
        )
        markets: list[MarketCandidate] = []
        for market in payload.get("markets", [])[:max_markets]:
            market_ticker = self.collector_store.upsert_market_instance(
                spec=self.spec,
                market=market,
                observed_at=now,
            )
            self.event_log.append(
                run_id=run_id,
                market_ticker=market_ticker,
                source="kalshi_rest",
                source_event_id=f"{run_id}:{market_ticker}:market",
                received_at=now,
                source_timestamp=parse_market_time(market.get("updated_time"), now),
                schema_version=MARKET_SNAPSHOT_SCHEMA,
                payload={"market": dict(market)},
            )
            self.event_log.append(
                run_id=run_id,
                market_ticker=market_ticker,
                source="kalshi_rest",
                source_event_id=f"{run_id}:{market_ticker}:orderbook",
                received_at=now,
                source_timestamp=now - timedelta(seconds=1),
                schema_version=ORDERBOOK_SNAPSHOT_SCHEMA,
                payload={"orderbook": dict(self.kalshi_client.get_orderbook(market_ticker))},
            )
            self._append_synthetic_kalshi_live_inputs(run_id, market_ticker, market, now)
            CoinbaseFeatureAdapter(
                database_url=self.database_url,
                client=self.coinbase_client,
                product_id=settings_from_env().coinbase_product_id,
                granularity_seconds=settings_from_env().coinbase_granularity_seconds,
                lookback_minutes=settings_from_env().coinbase_lookback_minutes,
            ).collect_feature_event(
                run_id=run_id,
                market_ticker=market_ticker,
                decision_timestamp=now,
                received_at=now,
            )
            markets.append(
                MarketCandidate(
                    market_ticker=market_ticker,
                    open_time=parse_market_time(market.get("open_time"), now),
                    close_time=parse_market_time(
                        market.get("close_time")
                        or market.get("expected_expiration_time")
                        or market.get("expiration_time"),
                        now + timedelta(minutes=self.spec.horizon_minutes),
                    ),
                    status=str(market.get("status") or "open"),
                    metadata=dict(market),
                )
            )
        return markets

    def _append_synthetic_kalshi_live_inputs(
        self,
        run_id: str,
        market_ticker: str,
        market: Mapping[str, Any],
        now: datetime,
    ) -> None:
        source_ts = now - timedelta(seconds=30)
        price = float(market.get("yes_ask_dollars") or market.get("yes_bid_dollars") or 0.50)
        self.event_log.append(
            run_id=run_id,
            market_ticker=market_ticker,
            source="kalshi_rest",
            source_event_id=f"{run_id}:{market_ticker}:candlestick",
            received_at=now,
            source_timestamp=source_ts,
            schema_version="kalshi.candlestick_snapshot.v1",
            payload={
                "candlestick": {
                    "candle_end_time": source_ts.isoformat(),
                    "price_close_dollars": price,
                    "yes_bid_close_dollars": market.get("yes_bid_dollars"),
                    "yes_ask_close_dollars": market.get("yes_ask_dollars"),
                    "no_bid_close_dollars": market.get("no_bid_dollars"),
                    "no_ask_close_dollars": market.get("no_ask_dollars"),
                    "volume_fp": market.get("volume") or 1.0,
                    "open_interest_fp": market.get("open_interest") or 1.0,
                }
            },
        )
        self.event_log.append(
            run_id=run_id,
            market_ticker=market_ticker,
            source="kalshi_rest",
            source_event_id=f"{run_id}:{market_ticker}:trade",
            received_at=now,
            source_timestamp=source_ts,
            schema_version="kalshi.trade_snapshot.v1",
            payload={
                "trade": {
                    "trade_timestamp": source_ts.isoformat(),
                    "yes_price_dollars": price,
                    "no_price_dollars": 1.0 - price,
                    "price_dollars": price,
                    "count_fp": 1.0,
                }
            },
        )

    def _handle_market(
        self,
        *,
        run_id: str,
        market: MarketCandidate,
        decision_timestamp: datetime,
        daily_realized_pnl_dollars: float,
    ) -> StrategyMarketOutcome:
        latency: dict[str, float] = {}
        started = time.perf_counter()
        try:
            feature_build = CurrentMvpFeatureRowBuilder(self.database_url).build(
                run_id=run_id,
                market_ticker=market.market_ticker,
                model_id=self.model_id,
                policy=self.policy,
                decision_timestamp=decision_timestamp,
            )
        except (
            MissingFeatureEventsError,
            MissingCurrentMvpFeatureError,
            NoLookaheadViolationError,
            ArtifactLoadError,
        ) as exc:
            latency["feature_construction_ms"] = elapsed_ms(started)
            return fresh_outcome(
                run_id=run_id,
                market_ticker=market.market_ticker,
                decision_timestamp=decision_timestamp,
                status="skipped",
                reason="missing_live_features",
                latency_checkpoints={"ingestion_ms": 0.0, **latency},
                metadata={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "runtime_mode": RuntimeMode.PAPER.value,
                    "live_orders_sent": 0,
                },
            )
        latency["feature_construction_ms"] = elapsed_ms(started)
        started = time.perf_counter()
        probability_yes = self.policy.predict_yes_probability(feature_build.feature_row.feature_values)
        latency["model_inference_ms"] = elapsed_ms(started)
        started = time.perf_counter()
        decision = DecisionRepository(self.database_url).persist(
            DecisionEngine().evaluate(
                build_decision_input(
                    spec=self.spec,
                    feature_row=feature_build.feature_row,
                    probability_yes=probability_yes,
                )
            )
        )
        latency["decisioning_ms"] = elapsed_ms(started)
        started = time.perf_counter()
        risk = RiskDecisionRepository(self.database_url).persist(
            RiskGate().evaluate(
                decision=decision,
                policy=RiskPolicy.from_spec(self.spec),
                state=RiskState(
                    trading_day=date.fromisoformat(decision_timestamp.date().isoformat()),
                    realized_pnl_dollars=daily_realized_pnl_dollars,
                ),
            )
        )
        latency["risk_ms"] = elapsed_ms(started)

        paper_order_id = None
        paper_status = None
        if risk.order_intent is not None:
            started = time.perf_counter()
            paper = PaperIocExecutor(self.database_url).execute(
                order_intent_id=risk.order_intent.order_intent_id,
                liquidity=PaperLiquidity(
                    side=risk.order_intent.side,
                    available_price_dollars=risk.order_intent.price_dollars,
                    available_quantity=risk.order_intent.quantity,
                    mark_price_dollars=risk.order_intent.price_dollars,
                ),
                executed_at=decision_timestamp,
            )
            latency["paper_execution_ms"] = elapsed_ms(started)
            paper_order_id = paper.paper_order_id
            paper_status = paper.status

        status = "handled" if risk.status == "approved" else "skipped"
        reason = decision.skip_reason or risk.reason
        return fresh_outcome(
            run_id=run_id,
            market_ticker=market.market_ticker,
            decision_timestamp=decision_timestamp,
            status=status,
            reason=reason,
            decision_id=decision.decision_id,
            risk_decision_id=risk.risk_decision_id,
            paper_order_id=paper_order_id,
            latency_checkpoints={"ingestion_ms": 0.0, **latency},
            metadata={
                "probability_yes": probability_yes,
                "decision_outcome": decision.outcome,
                "selected_side": decision.selected_side,
                "selected_ev_dollars": decision.selected_ev_dollars,
                "intended_quantity": decision.intended_quantity,
                "risk_status": risk.status,
                "paper_status": paper_status,
                "runtime_mode": RuntimeMode.PAPER.value,
                "live_orders_sent": 0,
            },
        )


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def parse_market_time(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str) and value:
        try:
            return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return ensure_utc(fallback)
    return ensure_utc(fallback)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-strategy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("paper-cycle", help="Run one bounded live-data paper cycle")
    run.add_argument("--now", default=None)
    run.add_argument("--max-markets", type=int, default=1)
    run.add_argument("--daily-realized-pnl-dollars", type=float, default=0.0)
    run.add_argument("--source", choices=("fixture",), default="fixture")
    status = subparsers.add_parser("status", help="Show latest strategy state")
    status.add_argument("--run-id", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    store = StrategyRunRepository(settings.database_url)
    if args.command == "paper-cycle":
        policy = load_pinned_model_policy_from_settings(settings)
        model = register_loaded_model(database_url=settings.database_url, policy=policy)
        now = (
            datetime.fromisoformat(args.now.replace("Z", "+00:00"))
            if args.now
            else datetime.now(UTC)
        )
        result = LiveDataPaperRunner(
            database_url=settings.database_url,
            policy=policy,
            model_id=model.model_id,
        ).run_one_cycle(
            now=now,
            max_markets=args.max_markets,
            daily_realized_pnl_dollars=args.daily_realized_pnl_dollars,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "status":
        run_id = args.run_id
        print(
            json.dumps(
                {
                    "latest_run": store.latest_run(),
                    "counts": store.counts(run_id=run_id),
                    "latest_outcomes": store.latest_outcomes(run_id=run_id, limit=10),
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
