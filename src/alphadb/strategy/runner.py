"""Live-data strategy runners for KXBTC15M."""

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
from alphadb.collectors.coinbase import (
    CoinbaseClient,
    CoinbaseFeatureAdapter,
    FixtureCoinbaseClient,
    HttpCoinbaseClient,
)
from alphadb.collectors.kalshi_rest import (
    FixtureKalshiRestClient,
    HttpKalshiRestClient,
    KalshiRestClient,
    CollectorRunStore,
    MARKET_SNAPSHOT_SCHEMA,
    ORDERBOOK_SNAPSHOT_SCHEMA,
)
from alphadb.config import Settings, settings_from_env
from alphadb.decision_engine.engine import (
    DecisionPolicy,
    DecisionEngine,
    DecisionRepository,
    build_decision_input,
)
from alphadb.events.log import RawEventLog
from alphadb.features.current_mvp import CurrentMvpFeatureRowBuilder, MissingCurrentMvpFeatureError
from alphadb.features.ledger import MissingFeatureEventsError, NoLookaheadViolationError
from alphadb.live_orders import (
    GatedLiveKalshiOrderAdapter,
    KalshiLiveOrderClient,
    LiveOrderError,
    LiveOrderRepository,
)
from alphadb.markets.registry import default_market_registry
from alphadb.markets.spec import MarketSpec
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


@dataclass(frozen=True)
class LiveDataStrategyLoopResult:
    run_id: str
    runtime_mode: str
    status: str
    cycles_completed: int
    latest_result: LiveDataPaperCycleResult | None
    error_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "runtime_mode": self.runtime_mode,
            "status": self.status,
            "cycles_completed": self.cycles_completed,
            "latest_result": None if self.latest_result is None else self.latest_result.as_dict(),
            "error_reason": self.error_reason,
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
        settings: Settings | None = None,
    ):
        self.database_url = database_url
        self.policy = policy
        self.model_id = model_id
        self.settings = settings or settings_from_env()
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
        keep_run_open: bool = False,
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
                    "live_stake_cap_dollars": self.settings.live_stake_cap_dollars,
                    "max_daily_loss_dollars": self.settings.max_daily_loss_dollars,
                    "min_ev_dollars": self.settings.min_ev_dollars,
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
                runtime_mode=RuntimeMode.PAPER,
                execute_paper=True,
            )

        scan = scheduler.scan(
            run_id=run_id,
            markets=markets,
            now=now,
            handler=handler,
            keep_run_open=keep_run_open,
        )
        cycle_counts = {f"cycle_{key}": value for key, value in scan.as_counts().items()}
        return LiveDataPaperCycleResult(
            run_id=run_id,
            market_ticker=markets[0].market_ticker if markets else None,
            outcome=scan.outcomes[0] if scan.outcomes else None,
            counts={
                **scan.as_counts(),
                **self.strategy_store.counts(run_id=run_id),
                **cycle_counts,
            },
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
                product_id=self.settings.coinbase_product_id,
                granularity_seconds=self.settings.coinbase_granularity_seconds,
                lookback_minutes=self.settings.coinbase_lookback_minutes,
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
        runtime_mode: RuntimeMode,
        execute_paper: bool,
        live_order_adapter: GatedLiveKalshiOrderAdapter | None = None,
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
                    "runtime_mode": runtime_mode.value,
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
                    policy=decision_policy_from_settings(self.spec, self.settings),
                )
            )
        )
        latency["decisioning_ms"] = elapsed_ms(started)
        started = time.perf_counter()
        risk = RiskDecisionRepository(self.database_url).persist(
            RiskGate().evaluate(
                decision=decision,
                policy=risk_policy_from_settings(self.spec, self.settings),
                state=RiskState(
                    trading_day=date.fromisoformat(decision_timestamp.date().isoformat()),
                    realized_pnl_dollars=daily_realized_pnl_dollars,
                ),
            )
        )
        latency["risk_ms"] = elapsed_ms(started)

        paper_order_id = None
        paper_status = None
        if execute_paper and risk.order_intent is not None:
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

        live_order_attempt_id = None
        live_order_status = None
        live_orders_sent = 0
        live_order_error_message = None
        if live_order_adapter is not None and risk.order_intent is not None:
            started = time.perf_counter()
            try:
                attempt = live_order_adapter.submit_order_intent(
                    order_intent_id=risk.order_intent.order_intent_id,
                    settings=self.settings,
                )
                live_order_attempt_id = attempt.live_order_attempt_id
                live_order_status = attempt.status
                live_orders_sent = 1 if attempt.status in {"submitted", "accepted"} else 0
                if attempt.status not in {"submitted", "accepted"}:
                    live_order_error_message = f"live order returned status {attempt.status}"
            except LiveOrderError as exc:
                live_order_status = "error"
                live_order_error_message = str(exc)
            latency["live_execution_ms"] = elapsed_ms(started)

        status = "handled" if risk.status == "approved" else "skipped"
        reason = decision.skip_reason or risk.reason
        if live_order_error_message is not None:
            status = "error"
            reason = "live_order_error"
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
                "runtime_mode": runtime_mode.value,
                "live_order_attempt_id": live_order_attempt_id,
                "live_order_status": live_order_status,
                "live_order_error_message": live_order_error_message,
                "live_orders_sent": live_orders_sent,
            },
        )

    def run_loop(
        self,
        *,
        poll_seconds: int,
        max_markets: int,
        max_cycles: int | None = None,
        duration_seconds: int | None = None,
        stop_on_error: bool = True,
    ) -> LiveDataStrategyLoopResult:
        return run_strategy_loop(
            runner=self,
            runtime_mode=RuntimeMode.PAPER,
            poll_seconds=poll_seconds,
            max_markets=max_markets,
            max_cycles=max_cycles,
            duration_seconds=duration_seconds,
            stop_on_error=stop_on_error,
        )


class LiveDataGatedLiveRunner(LiveDataPaperRunner):
    def __init__(
        self,
        *,
        database_url: str,
        policy: PinnedModelPolicy,
        model_id: str,
        settings: Settings | None = None,
        kalshi_client: KalshiRestClient | None = None,
        coinbase_client: CoinbaseClient | None = None,
        live_order_client: KalshiLiveOrderClient | None = None,
    ):
        settings = settings or settings_from_env()
        super().__init__(
            database_url=database_url,
            policy=policy,
            model_id=model_id,
            kalshi_client=kalshi_client or HttpKalshiRestClient(settings.kalshi_base_url),
            coinbase_client=coinbase_client or HttpCoinbaseClient(),
            settings=settings,
        )
        self.live_order_adapter = GatedLiveKalshiOrderAdapter(
            database_url=database_url,
            client=live_order_client,
        )

    def run_one_cycle(
        self,
        *,
        run_id: str | None = None,
        now: datetime | None = None,
        max_markets: int = 1,
        daily_realized_pnl_dollars: float = 0.0,
        keep_run_open: bool = False,
    ) -> LiveDataPaperCycleResult:
        now = ensure_utc(now or datetime.now(UTC))
        guard = evaluate_runtime_guard(self.settings)
        if not guard.can_submit_live_orders:
            raise LiveOrderError(f"gated-live runner denied: {guard.denial_reason}")
        if run_id is None:
            run = self.strategy_store.start_run(
                market_series=self.spec.series,
                runtime_mode=RuntimeMode.GATED_LIVE,
                started_at=now,
                metadata={
                    "model_artifact_sha256": self.policy.model_artifact_sha256,
                    "feature_schema_sha256": self.policy.feature_schema_sha256,
                    "live_stake_cap_dollars": self.settings.live_stake_cap_dollars,
                    "max_daily_loss_dollars": self.settings.max_daily_loss_dollars,
                    "min_ev_dollars": self.settings.min_ev_dollars,
                    "runner": "gated-live",
                },
            )
            run_id = run.run_id

        markets = self._collect_fixture_like_inputs(run_id=run_id, now=now, max_markets=max_markets)
        scheduler = Kxbtc15mHandledMarketScheduler(database_url=self.database_url, spec=self.spec)

        def handler(market: MarketCandidate, decision_timestamp: datetime) -> StrategyMarketOutcome:
            risk_pnl = self._conservative_daily_risk_pnl(
                trading_day=decision_timestamp.date(),
                reported_realized_pnl_dollars=daily_realized_pnl_dollars,
            )
            return self._handle_market(
                run_id=run_id,
                market=market,
                decision_timestamp=decision_timestamp,
                daily_realized_pnl_dollars=risk_pnl,
                runtime_mode=RuntimeMode.GATED_LIVE,
                execute_paper=False,
                live_order_adapter=self.live_order_adapter,
            )

        scan = scheduler.scan(
            run_id=run_id,
            markets=markets,
            now=now,
            handler=handler,
            keep_run_open=keep_run_open,
        )
        cycle_counts = {f"cycle_{key}": value for key, value in scan.as_counts().items()}
        return LiveDataPaperCycleResult(
            run_id=run_id,
            market_ticker=markets[0].market_ticker if markets else None,
            outcome=scan.outcomes[0] if scan.outcomes else None,
            counts={
                **scan.as_counts(),
                **self.strategy_store.counts(run_id=run_id),
                **cycle_counts,
            },
        )

    def _conservative_daily_risk_pnl(
        self,
        *,
        trading_day: date,
        reported_realized_pnl_dollars: float,
    ) -> float:
        submitted_cost = LiveOrderRepository(self.database_url).submitted_max_cost_dollars(
            trading_day=trading_day
        )
        realized_loss = max(0.0, -reported_realized_pnl_dollars)
        return -max(realized_loss, submitted_cost)

    def run_loop(
        self,
        *,
        poll_seconds: int,
        max_markets: int,
        max_cycles: int | None = None,
        duration_seconds: int | None = None,
        stop_on_error: bool = True,
    ) -> LiveDataStrategyLoopResult:
        return run_strategy_loop(
            runner=self,
            runtime_mode=RuntimeMode.GATED_LIVE,
            poll_seconds=poll_seconds,
            max_markets=max_markets,
            max_cycles=max_cycles,
            duration_seconds=duration_seconds,
            stop_on_error=stop_on_error,
        )


def run_strategy_loop(
    *,
    runner: LiveDataPaperRunner,
    runtime_mode: RuntimeMode,
    poll_seconds: int,
    max_markets: int,
    max_cycles: int | None = None,
    duration_seconds: int | None = None,
    stop_on_error: bool = True,
) -> LiveDataStrategyLoopResult:
    if poll_seconds < 0:
        raise ValueError("poll_seconds must be non-negative")
    if max_cycles is not None and max_cycles < 1:
        raise ValueError("max_cycles must be at least 1 when provided")
    if duration_seconds is not None and duration_seconds < 1:
        raise ValueError("duration_seconds must be at least 1 when provided")

    run_id: str | None = None
    latest: LiveDataPaperCycleResult | None = None
    cycles = 0
    started = time.monotonic()

    while True:
        if duration_seconds is not None and time.monotonic() - started >= duration_seconds:
            break
        latest = runner.run_one_cycle(
            run_id=run_id,
            now=datetime.now(UTC),
            max_markets=max_markets,
            keep_run_open=True,
        )
        run_id = latest.run_id
        cycles += 1
        if stop_on_error and int(latest.counts.get("cycle_errored", 0)) > 0:
            runner.strategy_store.finish_run(
                run_id=run_id,
                status="error",
                metadata_patch={"loop_status": "stopped_on_error"},
            )
            return LiveDataStrategyLoopResult(
                run_id=run_id,
                runtime_mode=runtime_mode.value,
                status="stopped_on_error",
                cycles_completed=cycles,
                latest_result=latest,
                error_reason="cycle_errored",
            )
        if max_cycles is not None and cycles >= max_cycles:
            break
        if poll_seconds:
            time.sleep(poll_seconds)

    if run_id is None:
        run_id = ""
    else:
        runner.strategy_store.finish_run(
            run_id=run_id,
            status="completed",
            metadata_patch={"loop_status": "completed", "cycles_completed": cycles},
        )
    return LiveDataStrategyLoopResult(
        run_id=run_id,
        runtime_mode=runtime_mode.value,
        status="completed",
        cycles_completed=cycles,
        latest_result=latest,
    )


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def decision_policy_from_settings(spec: MarketSpec, settings: Settings) -> DecisionPolicy:
    return DecisionPolicy(
        min_ev_dollars=settings.min_ev_dollars,
        max_cost_dollars=settings.live_stake_cap_dollars,
        time_in_force=spec.trading_cutoffs.time_in_force,
    )


def risk_policy_from_settings(spec: MarketSpec, settings: Settings) -> RiskPolicy:
    return RiskPolicy(
        max_daily_loss_dollars=settings.max_daily_loss_dollars,
        per_trade_max_cost_dollars=settings.live_stake_cap_dollars,
        fail_closed=True,
        time_in_force=spec.trading_cutoffs.time_in_force,
    )


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
    run.add_argument("--source", choices=("fixture", "live"), default="fixture")
    paper_loop = subparsers.add_parser("paper-loop", help="Run live-data paper cycles continuously")
    paper_loop.add_argument("--source", choices=("fixture", "live"), default="live")
    paper_loop.add_argument("--max-markets", type=int, default=3)
    paper_loop.add_argument("--poll-seconds", type=int, default=None)
    paper_loop.add_argument("--max-cycles", type=int, default=None)
    paper_loop.add_argument("--duration-minutes", type=float, default=None)
    paper_loop.add_argument("--no-stop-on-error", action="store_true")
    live_cycle = subparsers.add_parser(
        "gated-live-cycle",
        help="Run one live-money cycle using live market data",
    )
    live_cycle.add_argument("--max-markets", type=int, default=1)
    live_cycle.add_argument("--daily-realized-pnl-dollars", type=float, default=0.0)
    live_loop = subparsers.add_parser(
        "gated-live-loop",
        help="Run live-money cycles continuously using live market data",
    )
    live_loop.add_argument("--max-markets", type=int, default=3)
    live_loop.add_argument("--poll-seconds", type=int, default=None)
    live_loop.add_argument("--max-cycles", type=int, default=None)
    live_loop.add_argument("--duration-minutes", type=float, default=None)
    live_loop.add_argument("--no-stop-on-error", action="store_true")
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
        kalshi_client, coinbase_client = market_data_clients(args.source, settings)
        now = (
            datetime.fromisoformat(args.now.replace("Z", "+00:00"))
            if args.now
            else datetime.now(UTC)
        )
        result = LiveDataPaperRunner(
            database_url=settings.database_url,
            policy=policy,
            model_id=model.model_id,
            kalshi_client=kalshi_client,
            coinbase_client=coinbase_client,
            settings=settings,
        ).run_one_cycle(
            now=now,
            max_markets=args.max_markets,
            daily_realized_pnl_dollars=args.daily_realized_pnl_dollars,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "paper-loop":
        policy = load_pinned_model_policy_from_settings(settings)
        model = register_loaded_model(database_url=settings.database_url, policy=policy)
        kalshi_client, coinbase_client = market_data_clients(args.source, settings)
        result = LiveDataPaperRunner(
            database_url=settings.database_url,
            policy=policy,
            model_id=model.model_id,
            kalshi_client=kalshi_client,
            coinbase_client=coinbase_client,
            settings=settings,
        ).run_loop(
            poll_seconds=args.poll_seconds
            if args.poll_seconds is not None
            else settings.strategy_poll_seconds,
            max_markets=args.max_markets,
            max_cycles=args.max_cycles,
            duration_seconds=duration_minutes_to_seconds(args.duration_minutes),
            stop_on_error=not args.no_stop_on_error,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True, default=str))
        return 1 if result.status == "stopped_on_error" else 0
    if args.command == "gated-live-cycle":
        policy = load_pinned_model_policy_from_settings(settings)
        model = register_loaded_model(database_url=settings.database_url, policy=policy)
        result = LiveDataGatedLiveRunner(
            database_url=settings.database_url,
            policy=policy,
            model_id=model.model_id,
            settings=settings,
        ).run_one_cycle(
            max_markets=args.max_markets,
            daily_realized_pnl_dollars=args.daily_realized_pnl_dollars,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True, default=str))
        return 1 if result.outcome is not None and result.outcome.status == "error" else 0
    if args.command == "gated-live-loop":
        policy = load_pinned_model_policy_from_settings(settings)
        model = register_loaded_model(database_url=settings.database_url, policy=policy)
        result = LiveDataGatedLiveRunner(
            database_url=settings.database_url,
            policy=policy,
            model_id=model.model_id,
            settings=settings,
        ).run_loop(
            poll_seconds=args.poll_seconds
            if args.poll_seconds is not None
            else settings.strategy_poll_seconds,
            max_markets=args.max_markets,
            max_cycles=args.max_cycles,
            duration_seconds=duration_minutes_to_seconds(args.duration_minutes),
            stop_on_error=not args.no_stop_on_error,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True, default=str))
        return 1 if result.status == "stopped_on_error" else 0
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


def market_data_clients(source: str, settings: Settings) -> tuple[KalshiRestClient, CoinbaseClient]:
    if source == "fixture":
        return FixtureKalshiRestClient(), FixtureCoinbaseClient()
    if source == "live":
        return HttpKalshiRestClient(settings.kalshi_base_url), HttpCoinbaseClient()
    raise ValueError(f"unsupported strategy source: {source}")


def duration_minutes_to_seconds(value: float | None) -> int | None:
    if value is None:
        return None
    return max(1, int(value * 60))
