"""Capped live-money fair-value canary job."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib import parse, request
from uuid import uuid4
from zoneinfo import ZoneInfo

from alphadb.config import Settings, settings_from_env
from alphadb.live_orders import (
    HttpKalshiLiveOrderClient,
    KalshiLiveOrderClient,
    LiveOrderAttempt,
    LiveOrderRepository,
    exchange_response_accepted,
    materialize_private_key_from_env,
)
from alphadb.live_authority import (
    LIVE_DECISION_AUTHORITY_LEASE_SCHEMA,
    LiveDecisionAuthorityLease,
    LiveDecisionAuthorityLeaseRepository,
)
from alphadb.live_runtime import (
    EXPENSIVE_YES_LIVE_STRATEGY,
    FAIR_VALUE_LIVE_STRATEGY,
    MARKET_CONTEXT_BRTI_PRIMARY,
    MARKET_CONTEXT_COINBASE_PRIMARY,
    LiveRunStatusRepository,
    LiveRuntimeConfigRepository,
    build_fair_value_live_status,
    validate_market_context_source,
)
from alphadb.live_edge_attribution import build_live_edge_attribution
from alphadb.live_risk import (
    DEFAULT_LIVE_RISK_STALE_SECONDS,
    LiveRiskAdmissionRepository,
    LiveRiskAdmissionResult,
    LiveRiskAdmissionState,
    state_denial_reason,
)
from alphadb.live_risk_refresh import (
    BoundedRefreshLimits,
    bounded_refresh_before_admission,
)
from alphadb.model_evaluation.fair_value_live import (
    DEFAULT_BRTI_FUTURE_TOLERANCE_SECONDS,
    FairValueDecisionRowCollector,
    FairValueDecisionRowCollectorConfig,
    make_coinbase_client,
    make_kalshi_client,
)
from alphadb.model_evaluation.fair_value_replay import (
    FairValueReplayConfig,
    decide_trade,
    parse_min_edge_values,
    replay_sort_key,
)
from alphadb.model_evaluation.io import file_sha256, write_json
from alphadb.model_evaluation.metrics import optional_float, taker_fee
from alphadb.runtime import evaluate_runtime_guard

FAIR_VALUE_LIVE_JOB_SCHEMA = "kxbtc_fair_value_live_trading_job.v1"
FAIR_VALUE_LIVE_ATTEMPTS_SCHEMA = "kxbtc_fair_value_live_order_attempts.v1"
FAIR_VALUE_LIVE_RECONCILIATION_SCHEMA = "kxbtc_fair_value_live_reconciliation.v1"
FAIR_VALUE_LIVE_LOCK_SCHEMA = "kxbtc_fair_value_live_run_lock.v1"
FAIR_VALUE_LIVE_DAILY_LOSS_ACCOUNTING_SCHEMA = "kxbtc_fair_value_live_daily_loss_accounting.v1"
FAIR_VALUE_LIVE_LOCK_TTL_SECONDS = 180
DEFAULT_LIVE_RISK_TIMEZONE = "America/Los_Angeles"
RuntimeConfigSource = Literal["auto", "postgres", "cli"]
LiveDecisionPolicy = Literal["fair_value", "expensive_yes"]
AWS_LIKE_ENVIRONMENTS = {"aws", "prod", "production"}


@dataclass(frozen=True)
class FairValueLiveTradingJobConfig:
    output_root: Path
    strategy: str = FAIR_VALUE_LIVE_STRATEGY
    decision_policy: LiveDecisionPolicy = "fair_value"
    source: str = "fixture"
    coinbase_source: str = "fixture"
    market_context_source: str = MARKET_CONTEXT_COINBASE_PRIMARY
    max_markets: int = 20
    min_edge: float = 0.0
    min_contract_price: float = 0.25
    min_edge_values: tuple[float, ...] = (0.0, 0.05, 0.10)
    max_order_dollars: float = 5.0
    max_ticker_exposure_dollars: float = 5.0
    max_daily_loss_dollars: float = 50.0
    selection_market_count: int = 1
    holdout_market_count: int = 1
    step_market_count: int | None = None
    s3_prefix: str | None = None
    submit_live_orders: bool = False
    runtime_config_source: RuntimeConfigSource = "auto"
    live_risk_timezone: str = DEFAULT_LIVE_RISK_TIMEZONE
    live_risk_state_stale_seconds: int = DEFAULT_LIVE_RISK_STALE_SECONDS
    live_risk_refresh_max_lookup_count: int = 3
    live_risk_refresh_timeout_seconds: float = 2.0
    live_risk_refresh_per_lookup_timeout_seconds: float = 1.0
    quote_stale_seconds: int = 15
    coinbase_feature_stale_seconds: int = 90
    brti_future_tolerance_seconds: float = DEFAULT_BRTI_FUTURE_TOLERANCE_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_root": str(self.output_root),
            "strategy": self.strategy,
            "decision_policy": self.decision_policy,
            "source": self.source,
            "coinbase_source": self.coinbase_source,
            "market_context_source": self.market_context_source,
            "max_markets": self.max_markets,
            "min_edge": self.min_edge,
            "min_contract_price": self.min_contract_price,
            "min_edge_values": list(self.min_edge_values),
            "max_order_dollars": self.max_order_dollars,
            "max_ticker_exposure_dollars": self.max_ticker_exposure_dollars,
            "max_daily_loss_dollars": self.max_daily_loss_dollars,
            "selection_market_count": self.selection_market_count,
            "holdout_market_count": self.holdout_market_count,
            "step_market_count": self.step_market_count,
            "s3_prefix": self.s3_prefix,
            "submit_live_orders": self.submit_live_orders,
            "runtime_config_source": self.runtime_config_source,
            "live_risk_timezone": self.live_risk_timezone,
            "live_risk_state_stale_seconds": self.live_risk_state_stale_seconds,
            "live_risk_refresh_max_lookup_count": self.live_risk_refresh_max_lookup_count,
            "live_risk_refresh_timeout_seconds": self.live_risk_refresh_timeout_seconds,
            "live_risk_refresh_per_lookup_timeout_seconds": (
                self.live_risk_refresh_per_lookup_timeout_seconds
            ),
            "quote_stale_seconds": self.quote_stale_seconds,
            "coinbase_feature_stale_seconds": self.coinbase_feature_stale_seconds,
            "brti_future_tolerance_seconds": self.brti_future_tolerance_seconds,
        }


class FairValueLiveTradingJob:
    def __init__(
        self,
        *,
        config: FairValueLiveTradingJobConfig,
        settings: Settings | None = None,
        order_client: KalshiLiveOrderClient | None = None,
    ):
        self.config = config
        validate_market_context_source(config.market_context_source)
        if config.brti_future_tolerance_seconds < 0:
            raise ValueError("brti_future_tolerance_seconds must be non-negative")
        self._settings = settings
        self.order_client = order_client or HttpKalshiLiveOrderClient()

    def run(self, *, now: datetime | None = None) -> dict[str, Any]:
        settings, credential_materialization = settings_with_materialized_private_key(self._settings)
        original_config = self.config
        generated_at = ensure_utc(now or datetime.now(UTC))
        run_id = f"{live_run_id_prefix(self.config.strategy)}_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
        run_dir = self.config.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        timer = PhaseTimer()
        authority_phase = (
            "postgres_authority_lease"
            if should_use_postgres_authority_lease(self.config)
            else "live_run_lock"
        )
        with timer.phase(authority_phase):
            live_run_lock = acquire_live_run_lock(
                output_root=self.config.output_root,
                s3_prefix=self.config.s3_prefix,
                run_id=run_id,
                generated_at=generated_at,
                enabled=self.config.submit_live_orders,
                strategy=self.config.strategy,
                settings=settings,
                use_postgres_authority=should_use_postgres_authority_lease(self.config),
            )
        try:
            if not live_run_lock.acquired:
                attempt = lock_held_attempt(
                    run_id=run_id,
                    generated_at=generated_at,
                    live_run_lock=live_run_lock,
                    strategy=self.config.strategy,
                )
                timer.ensure_phases(
                    "postgres_authority_lease",
                    "runtime_config",
                    "collection",
                    "decision",
                    "freshness",
                    "risk_refresh",
                    "submit_attempt_persist",
                    "risk_admission",
                    "submit",
                    "status_materialization",
                    "artifact_write",
                )
                authority_denial_reason = live_run_lock.reason or "live_run_lock_held"
                return self._materialize_one_cycle_run(
                    run_dir=run_dir,
                    run_id=run_id,
                    generated_at=generated_at,
                    runtime_config=runtime_config_snapshot(
                        original_config,
                        reason=authority_denial_reason,
                    ),
                    collected=None,
                    selected_decision=None,
                    selected_row=None,
                    live_attempts=[attempt],
                    live_reconciliation=compact_live_reconciliation(
                        [attempt],
                        generated_at=generated_at,
                        max_ticker_exposure_dollars=original_config.max_ticker_exposure_dollars,
                    ),
                    admission_daily_loss_accounting=empty_live_risk_accounting(
                        generated_at=generated_at,
                        live_risk_timezone=original_config.live_risk_timezone,
                        reason=authority_denial_reason,
                    ),
                    daily_loss_accounting=empty_live_risk_accounting(
                        generated_at=generated_at,
                        live_risk_timezone=original_config.live_risk_timezone,
                        reason=authority_denial_reason,
                    ),
                    runtime_guard=runtime_guard_with_credential_materialization(
                        settings=settings,
                        credential_materialization=credential_materialization,
                    ).as_dict(),
                    live_run_lock=live_run_lock,
                    timer=timer,
                    require_postgres=False,
                    materialize_status=should_materialize_live_run_status(live_run_lock),
                )

            with timer.phase("runtime_config"):
                effective_config, runtime_config = resolve_live_runtime_config(
                    original_config,
                    settings=settings,
                )
                self.config = effective_config
                guard = runtime_guard_with_credential_materialization(
                    settings=settings,
                    credential_materialization=credential_materialization,
                )
            with timer.phase("collection"):
                collector = FairValueDecisionRowCollector(
                    kalshi_client=make_kalshi_client(self.config.source, settings),
                    coinbase_client=make_coinbase_client(self.config.coinbase_source),
                    settings=settings,
                    config=FairValueDecisionRowCollectorConfig(
                        max_markets=self.config.max_markets,
                        run_id=run_id,
                        source_mode=self.config.source,
                        coinbase_source_mode=self.config.coinbase_source,
                        market_context_source=self.config.market_context_source,
                        brti_future_tolerance_seconds=self.config.brti_future_tolerance_seconds,
                        include_coinbase_features=self.config.decision_policy == "fair_value",
                        include_fair_value_score=self.config.decision_policy == "fair_value",
                    ),
                )
                collected = collector.collect(now=generated_at).as_dict()
            with timer.phase("decision"):
                selected_pairs = select_live_decision_pairs(
                    collected.get("rows", []),
                    config=FairValueReplayConfig(
                        min_edge=self.config.min_edge,
                        min_contract_price=self.config.min_contract_price,
                        max_order_dollars=self.config.max_order_dollars,
                        max_loss_dollars=self.config.max_daily_loss_dollars,
                    ),
                    decision_policy=self.config.decision_policy,
                )
            with timer.phase("freshness"):
                selected_pairs = [
                    (
                        apply_live_freshness_gates(
                            decision,
                            row,
                            generated_at=generated_at,
                            quote_stale_seconds=self.config.quote_stale_seconds,
                            coinbase_feature_stale_seconds=self.config.coinbase_feature_stale_seconds,
                            require_coinbase_freshness=(
                                self.config.decision_policy == "fair_value"
                                and self.config.market_context_source
                                != MARKET_CONTEXT_BRTI_PRIMARY
                            ),
                        ),
                        row,
                    )
                    for decision, row in selected_pairs
                ]
            selected_decision, selected_row = selected_pairs[0]
            live_risk_day, _window_start, _window_end = live_risk_window(
                generated_at=generated_at,
                live_risk_timezone=self.config.live_risk_timezone,
            )
            admission_state: LiveRiskAdmissionState | None = None
            risk_state_read: Mapping[str, Any] = {
                "risk_state_bootstrapped": False,
                "risk_state_read_reason": "risk_state_not_required",
            }
            should_prepare_risk_state = (
                self.config.submit_live_orders
                and guard.can_submit_live_orders
                and any(decision.get("decision") == "trade" for decision, _row in selected_pairs)
            )
            if should_prepare_risk_state:
                with timer.phase("risk_state_read"):
                    admission_state, risk_state_read = live_risk_state_for_admission(
                        settings=settings,
                        strategy=self.config.strategy,
                        live_risk_day=live_risk_day,
                        generated_at=generated_at,
                        run_id=run_id,
                    )
                with timer.phase("risk_refresh"):
                    refresh_result = bounded_refresh_before_admission(
                        risk_repository=LiveRiskAdmissionRepository(settings.database_url),
                        order_repository=LiveOrderRepository(settings.database_url),
                        order_client=self.order_client,
                        settings=settings,
                        state=admission_state,
                        strategy=self.config.strategy,
                        live_risk_day=live_risk_day,
                        now=generated_at,
                        run_id=run_id,
                        stale_after_seconds=self.config.live_risk_state_stale_seconds,
                        limits=BoundedRefreshLimits(
                            max_lookup_count=self.config.live_risk_refresh_max_lookup_count,
                            max_elapsed_seconds=self.config.live_risk_refresh_timeout_seconds,
                            per_lookup_timeout_seconds=(
                                self.config.live_risk_refresh_per_lookup_timeout_seconds
                            ),
                        ),
                    )
                    risk_state_read = {
                        **dict(risk_state_read),
                        "risk_refresh": refresh_result.as_dict(),
                    }
                    if refresh_result.state is not None:
                        admission_state = refresh_result.state
            admission_daily_loss_accounting = {
                **live_risk_accounting_report(
                    admission_state,
                    generated_at=generated_at,
                    live_risk_timezone=self.config.live_risk_timezone,
                    stale_after_seconds=self.config.live_risk_state_stale_seconds,
                ),
                **dict(risk_state_read),
            }
            live_attempts: list[dict[str, Any]] = []
            risk_transition: LiveRiskAdmissionResult | None = None
            order_submit_at: datetime | None = None
            for decision, row in selected_pairs:
                live_attempt, attempt_risk_transition, attempt_submit_at = (
                    self._submit_one_cycle_attempt(
                        decision=decision,
                        decision_row=row,
                        settings=settings,
                        run_id=run_id,
                        generated_at=generated_at,
                        live_risk_day=live_risk_day,
                        admission_state=admission_state,
                        daily_loss_accounting=admission_daily_loss_accounting,
                        runtime_guard=guard.as_dict(),
                        live_run_lock=live_run_lock,
                        timer=timer,
                    )
                )
                live_attempts.append(live_attempt)
                if attempt_risk_transition is not None:
                    risk_transition = attempt_risk_transition
                    if attempt_risk_transition.state is not None:
                        admission_state = attempt_risk_transition.state
                if attempt_submit_at is not None:
                    order_submit_at = attempt_submit_at
            live_reconciliation = compact_live_reconciliation(
                live_attempts,
                generated_at=generated_at,
                max_ticker_exposure_dollars=self.config.max_ticker_exposure_dollars,
            )
            final_state = live_risk_state_for_day(
                settings=settings,
                strategy=self.config.strategy,
                live_risk_day=live_risk_day,
                apply_migrations=False,
            ) if self.config.submit_live_orders else None
            daily_loss_accounting = live_risk_accounting_report(
                final_state or admission_state,
                generated_at=generated_at,
                live_risk_timezone=self.config.live_risk_timezone,
                stale_after_seconds=self.config.live_risk_state_stale_seconds,
            )
            live_attempts_payload = {
                "schema_version": FAIR_VALUE_LIVE_ATTEMPTS_SCHEMA,
                "run_id": run_id,
                "strategy": self.config.strategy,
                "generated_at": generated_at.isoformat(),
                "admission_daily_loss_accounting": admission_daily_loss_accounting,
                "risk_transition": risk_transition.as_dict() if risk_transition else None,
                "skip_reasons": summarize_attempt_reasons(live_attempts),
                "attempts": live_attempts,
                "one_cycle": True,
            }
            live_attempts_payload["daily_loss_accounting"] = daily_loss_accounting
            if order_submit_at is not None:
                timer.order_submit_at = order_submit_at
            return self._materialize_one_cycle_run(
                run_dir=run_dir,
                run_id=run_id,
                generated_at=generated_at,
                runtime_config=runtime_config,
                collected=collected,
                selected_decision=selected_decision,
                selected_row=selected_row,
                live_attempts=live_attempts,
                live_reconciliation=live_reconciliation,
                admission_daily_loss_accounting=admission_daily_loss_accounting,
                daily_loss_accounting=daily_loss_accounting,
                runtime_guard=guard.as_dict(),
                live_run_lock=live_run_lock,
                timer=timer,
                require_postgres=runtime_config.get("source") == "dashboard_postgres",
                materialize_status=should_materialize_live_run_status(live_run_lock),
                live_attempts_payload=live_attempts_payload,
            )
        finally:
            self.config = original_config
            live_run_lock.release()

    def _submit_one_cycle_attempt(
        self,
        *,
        decision: Mapping[str, Any],
        decision_row: Mapping[str, Any] | None,
        settings: Settings,
        run_id: str,
        generated_at: datetime,
        live_risk_day: date,
        admission_state: LiveRiskAdmissionState | None,
        daily_loss_accounting: Mapping[str, Any],
        runtime_guard: Mapping[str, Any],
        live_run_lock: "LiveRunLock",
        timer: "PhaseTimer",
    ) -> tuple[dict[str, Any], LiveRiskAdmissionResult | None, datetime | None]:
        market_ticker = str(decision.get("ticker") or decision.get("market_ticker") or "")
        current_market_exposure = (
            admission_state.market_exposure_dollars(market_ticker) if admission_state else 0.0
        )
        market_remaining = max(
            0.0,
            self.config.max_ticker_exposure_dollars - current_market_exposure,
        )
        order = dict(decision)
        sized_order = (
            order_sized_to_market_cap(
                order,
                remaining_ticker_exposure_dollars=market_remaining,
            )
            if order.get("decision") == "trade"
            else None
        )
        effective_decision = dict(sized_order or order)
        request_payload = (
            live_order_request(effective_decision, run_id=run_id)
            if sized_order is not None
            else {}
        )
        max_loss = (
            float(effective_decision.get("max_loss_dollars") or 0.0)
            if sized_order is not None
            else 0.0
        )
        risk_before = admission_state.daily_loss_used_dollars if admission_state else 0.0
        freshness = live_decision_freshness(decision_row, generated_at=generated_at)
        attempt_id = f"{live_run_id_prefix(self.config.strategy)}_order_{uuid4().hex[:12]}"
        base = {
            "attempt_id": attempt_id,
            "live_order_attempt_id": attempt_id,
            "run_id": run_id,
            "strategy": self.config.strategy,
            "submitted_at": generated_at.isoformat(),
            "market_ticker": market_ticker,
            "side": effective_decision.get("side"),
            "decision": effective_decision,
            "original_decision": dict(decision),
            "source_row": dict(decision_row or {}),
            "request_payload": request_payload,
            "max_loss_dollars": round(max_loss, 6),
            "daily_loss_used_before_dollars": round(risk_before, 6),
            "daily_loss_accounting": dict(daily_loss_accounting),
            "market_exposure": {
                "market_ticker": market_ticker,
                "max_ticker_exposure_dollars": self.config.max_ticker_exposure_dollars,
                "used_before_dollars": round(current_market_exposure, 6),
                "remaining_before_dollars": round(market_remaining, 6),
                "intended_contracts": int(
                    decision.get("intended_contracts") or decision.get("contracts") or 0
                ),
                "sized_contracts": int(
                    effective_decision.get("intended_contracts")
                    or effective_decision.get("contracts")
                    or 0
                ),
            },
            "quote_source": (decision_row or {}).get("quote_source"),
            "quote_seen_at": freshness.get("quote_seen_at"),
            "quote_age_seconds": freshness.get("quote_age_seconds"),
            "freshness": freshness,
            "market_context_source": self.config.market_context_source,
            "runtime_guard": dict(runtime_guard),
            "live_run_lock": live_run_lock.as_dict(),
            "attempt_index": 0,
        }
        if live_run_lock.backend == "postgres":
            base["live_decision_authority_lease"] = live_run_lock.as_dict()
        if decision.get("decision") != "trade":
            return (
                {**base, "status": "skipped", "reason": str(decision.get("reason") or "no_trade")},
                None,
                None,
            )
        if sized_order is None:
            return ({**base, "status": "skipped", "reason": "market_exposure_cap_reached"}, None, None)
        if not self.config.submit_live_orders:
            return ({**base, "status": "skipped", "reason": "submit_live_orders_false"}, None, None)
        if not runtime_guard.get("can_submit_live_orders"):
            reason = str(runtime_guard.get("denial_reason") or "live_orders_disabled")
            return ({**base, "status": "skipped", "reason": reason}, None, None)
        try:
            materialize_private_key_from_env()
        except Exception as exc:
            return (
                {
                    **base,
                    "status": "error",
                    "reason": f"live_order_error:{type(exc).__name__}",
                    "response_payload": {"message": str(exc)},
                },
                None,
                None,
            )

        with timer.phase("risk_admission"):
            risk_result = LiveRiskAdmissionRepository(settings.database_url).admit_order(
                strategy=self.config.strategy,
                live_risk_day=live_risk_day,
                market_ticker=market_ticker,
                max_loss_dollars=max_loss,
                max_daily_loss_dollars=self.config.max_daily_loss_dollars,
                max_market_exposure_dollars=self.config.max_ticker_exposure_dollars,
                now=generated_at,
                stale_after_seconds=self.config.live_risk_state_stale_seconds,
                run_id=run_id,
                reservation_metadata={
                    "live_order_attempt_id": attempt_id,
                    "client_order_id": request_payload.get("client_order_id"),
                    "intended_side": effective_decision.get("side"),
                    "intended_price_dollars": effective_decision.get("price"),
                    "intended_quantity": effective_decision.get("contracts")
                    or effective_decision.get("intended_contracts"),
                    "intended_max_loss_dollars": round(max_loss, 6),
                },
            )
        base = {
            **base,
            "risk_admission": risk_result.as_dict(),
            "risk_reservation_id": risk_result.reservation_id,
        }
        if not risk_result.approved:
            return ({**base, "status": "skipped", "reason": risk_result.reason}, risk_result, None)

        order_submit_at = datetime.now(UTC)
        attempt_record = LiveOrderAttempt(
            live_order_attempt_id=attempt_id,
            order_intent_id=None,
            risk_decision_id=None,
            strategy=self.config.strategy,
            live_risk_day=live_risk_day,
            reservation_id=str(risk_result.reservation_id),
            market_ticker=market_ticker,
            client_order_id=str(request_payload.get("client_order_id") or ""),
            intended_side=str(effective_decision.get("side") or ""),
            intended_price_dollars=float(effective_decision.get("price") or 0.0),
            intended_quantity=float(
                effective_decision.get("contracts")
                or effective_decision.get("intended_contracts")
                or 0.0
            ),
            intended_max_loss_dollars=round(max_loss, 6),
            runtime_mode=str(runtime_guard.get("runtime_mode") or ""),
            status="submit_pending",
            guard_reason=None,
            request_payload=request_payload,
            submitted_at=order_submit_at,
        )
        try:
            with timer.phase("submit_attempt_persist"):
                LiveOrderRepository(settings.database_url).persist(attempt_record)
        except Exception as exc:
            transition = LiveRiskAdmissionRepository(settings.database_url).retain_reservation(
                strategy=self.config.strategy,
                live_risk_day=live_risk_day,
                reservation_id=str(risk_result.reservation_id),
                now=datetime.now(UTC),
            )
            return (
                {
                    **base,
                    "order_submit_at": order_submit_at.isoformat(),
                    "status": "error",
                    "reason": f"live_order_attempt_persist_error:{type(exc).__name__}",
                    "response_payload": {"message": str(exc)},
                    "risk_transition": transition.as_dict(),
                    "operational_state_attempt": attempt_record.as_dict(),
                },
                transition,
                order_submit_at,
            )
        try:
            with timer.phase("submit"):
                response = self.order_client.create_order(
                    request_payload=request_payload,
                    settings=settings,
                )
        except Exception as exc:
            try:
                recorded_attempt = LiveOrderRepository(settings.database_url).record_submit_error(
                    live_order_attempt_id=attempt_id,
                    exc=exc,
                    observed_at=datetime.now(UTC),
                )
            except Exception as record_exc:
                recorded_attempt = {
                    **attempt_record.as_dict(),
                    "record_error": f"{type(record_exc).__name__}: {record_exc}",
                }
            transition = LiveRiskAdmissionRepository(settings.database_url).retain_reservation(
                strategy=self.config.strategy,
                live_risk_day=live_risk_day,
                reservation_id=str(risk_result.reservation_id),
                now=datetime.now(UTC),
            )
            return (
                {
                    **base,
                    "order_submit_at": order_submit_at.isoformat(),
                    "status": "error",
                    "reason": f"live_order_error:{type(exc).__name__}",
                    "response_payload": {"message": str(exc)},
                    "risk_transition": transition.as_dict(),
                    "operational_state_attempt": recorded_attempt,
                },
                transition,
                order_submit_at,
            )
        fill_count = int(numeric_response_value(response, ("fill_count", "fill_count_fp")) or 0)
        accepted = exchange_response_accepted(response)
        recorded_attempt = LiveOrderRepository(settings.database_url).record_submit_response(
            live_order_attempt_id=attempt_id,
            response_payload=response,
            accepted=accepted,
            observed_at=datetime.now(UTC),
        )
        if accepted and fill_count > 0:
            transition = LiveRiskAdmissionRepository(settings.database_url).convert_reservation(
                strategy=self.config.strategy,
                live_risk_day=live_risk_day,
                reservation_id=str(risk_result.reservation_id),
                filled_max_loss_dollars=filled_max_loss_estimate(effective_decision, fill_count),
                now=datetime.now(UTC),
            )
        elif accepted:
            transition = LiveRiskAdmissionRepository(settings.database_url).release_reservation(
                strategy=self.config.strategy,
                live_risk_day=live_risk_day,
                reservation_id=str(risk_result.reservation_id),
                now=datetime.now(UTC),
            )
        else:
            transition = LiveRiskAdmissionRepository(settings.database_url).release_reservation(
                strategy=self.config.strategy,
                live_risk_day=live_risk_day,
                reservation_id=str(risk_result.reservation_id),
                now=datetime.now(UTC),
            )
        return (
            {
                **base,
                "order_submit_at": order_submit_at.isoformat(),
                "status": "submitted" if accepted else "rejected",
                "reason": "submitted" if accepted else "exchange_rejected",
                "response_payload": dict(response),
                "risk_transition": transition.as_dict(),
                "order_id": response.get("order_id"),
                "client_order_id": response.get("client_order_id")
                or request_payload.get("client_order_id"),
                "fill_count": fill_count,
                "operational_state_attempt": recorded_attempt,
                "remaining_count": numeric_response_value(
                    response,
                    ("remaining_count", "remaining_count_fp"),
                ),
            },
            transition,
            order_submit_at,
        )

    def _materialize_one_cycle_run(
        self,
        *,
        run_dir: Path,
        run_id: str,
        generated_at: datetime,
        runtime_config: Mapping[str, Any],
        collected: Mapping[str, Any] | None,
        selected_decision: Mapping[str, Any] | None,
        selected_row: Mapping[str, Any] | None,
        live_attempts: Sequence[Mapping[str, Any]],
        live_reconciliation: Mapping[str, Any],
        admission_daily_loss_accounting: Mapping[str, Any],
        daily_loss_accounting: Mapping[str, Any],
        runtime_guard: Mapping[str, Any],
        live_run_lock: "LiveRunLock",
        timer: "PhaseTimer",
        require_postgres: bool,
        materialize_status: bool,
        live_attempts_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        timer.ensure_phases(
            "live_run_lock",
            "postgres_authority_lease",
            "runtime_config",
            "collection",
            "decision",
            "freshness",
            "risk_state_read",
            "risk_refresh",
            "submit_attempt_persist",
            "risk_admission",
            "submit",
            "status_materialization",
            "artifact_write",
        )
        runtime_controls = {
            "strategy": self.config.strategy,
            "decision_policy": self.config.decision_policy,
            "report_only": False,
            "submit_live_orders_requested": self.config.submit_live_orders,
            "live_orders_enabled": bool(runtime_guard.get("can_submit_live_orders")),
            "orders_placed": sum(
                1 for attempt in live_attempts if attempt["status"] == "submitted"
            ),
            "filled_contracts": sum(
                int(attempt.get("fill_count") or 0) for attempt in live_attempts
            ),
            "max_order_dollars": self.config.max_order_dollars,
            "max_market_exposure_dollars": self.config.max_ticker_exposure_dollars,
            "max_ticker_exposure_dollars": self.config.max_ticker_exposure_dollars,
            "max_daily_loss_dollars": self.config.max_daily_loss_dollars,
            "min_edge": self.config.min_edge,
            "min_contract_price": self.config.min_contract_price,
            "market_context_source": self.config.market_context_source,
            "brti_future_tolerance_seconds": self.config.brti_future_tolerance_seconds,
            "admission_daily_loss_accounting": dict(admission_daily_loss_accounting),
            "daily_loss_accounting": dict(daily_loss_accounting),
            "runtime_guard": dict(runtime_guard),
            "live_run_lock": live_run_lock.as_dict(),
            "live_status_materialized": False,
        }
        if live_run_lock.backend == "postgres":
            runtime_controls["live_decision_authority_lease"] = live_run_lock.as_dict()
        latest_raw_attempt = dict(live_attempts[-1]) if live_attempts else {}
        attempt_timing = timer.snapshot(
            quote_seen_at=parse_datetime(latest_raw_attempt.get("quote_seen_at")),
            order_submit_at=parse_datetime(latest_raw_attempt.get("order_submit_at")),
        )
        attributed_attempts = [
            live_attempt_with_edge_attribution(
                attempt,
                config=self.config.as_dict(),
                runtime_config=runtime_config,
                runtime_controls=runtime_controls,
                timing=attempt_timing,
                decision_policy=self.config.decision_policy,
            )
            for attempt in live_attempts
        ]
        attributed_collected = live_decision_rows_with_candidate_attribution(
            collected,
            config=self.config.as_dict(),
            runtime_config=runtime_config,
            runtime_controls=runtime_controls,
            generated_at=generated_at,
            timing=attempt_timing,
            decision_policy=self.config.decision_policy,
            replay_config=FairValueReplayConfig(
                min_edge=self.config.min_edge,
                min_contract_price=self.config.min_contract_price,
                max_order_dollars=self.config.max_order_dollars,
                max_loss_dollars=self.config.max_daily_loss_dollars,
            ),
        )
        attempts_payload = dict(
            live_attempts_payload
            or {
                "schema_version": FAIR_VALUE_LIVE_ATTEMPTS_SCHEMA,
                "run_id": run_id,
                "strategy": self.config.strategy,
                "generated_at": generated_at.isoformat(),
                "admission_daily_loss_accounting": dict(admission_daily_loss_accounting),
                "daily_loss_accounting": dict(daily_loss_accounting),
                "skip_reasons": summarize_attempt_reasons(attributed_attempts),
                "attempts": attributed_attempts,
                "one_cycle": True,
            }
        )
        attempts_payload["attempts"] = attributed_attempts
        attempts_payload["skip_reasons"] = summarize_attempt_reasons(attributed_attempts)
        artifacts: dict[str, Path] = {
            "live_order_attempts": run_dir / "live_order_attempts.json",
            "live_reconciliation_report": run_dir / "live_reconciliation_report.json",
        }
        if attributed_collected is not None:
            artifacts["decision_rows"] = run_dir / "decision_rows.json"
        with timer.phase("artifact_write"):
            if attributed_collected is not None:
                write_json(artifacts["decision_rows"], attributed_collected)
            write_json(artifacts["live_order_attempts"], attempts_payload)
            write_json(artifacts["live_reconciliation_report"], live_reconciliation)

        collected_counts = as_mapping((attributed_collected or {}).get("counts"))
        selected_trade = (selected_decision or {}).get("decision") == "trade"
        latest_attempt = dict(attributed_attempts[-1]) if attributed_attempts else {}
        latest_freshness = as_mapping(latest_attempt.get("freshness"))
        latest_attribution = build_live_edge_attribution(
            decision=selected_decision,
            source_row=selected_row,
            config=self.config.as_dict(),
            runtime_config=runtime_config,
            runtime_controls=runtime_controls,
            freshness=latest_freshness,
            timing=attempt_timing,
        ) if self.config.decision_policy == "fair_value" else {}
        manifest = {
            "schema_version": FAIR_VALUE_LIVE_JOB_SCHEMA,
            "run_id": run_id,
            "strategy": self.config.strategy,
            "decision_policy": self.config.decision_policy,
            "generated_at": generated_at.isoformat(),
            "one_cycle": True,
            "hot_path_scope": "one_current_decision_no_replay_no_walk_forward_no_full_history",
            "config": self.config.as_dict(),
            "runtime_config": dict(runtime_config),
            "runtime_controls": dict(runtime_controls),
            "executable_quote": {
                "source": latest_attempt.get("quote_source"),
                "quote_seen_at": latest_attempt.get("quote_seen_at"),
                "max_quote_age_seconds": latest_attempt.get("quote_age_seconds"),
                "freshness": dict(latest_freshness),
            },
            "market_context": live_market_context_evidence(
                selected_row,
                config=self.config.as_dict(),
                freshness=latest_freshness,
            ),
            "live_edge_attribution": latest_attribution,
            "live_risk_admission_state": {
                "status": daily_loss_accounting.get("risk_state_status"),
                "reason": daily_loss_accounting.get("risk_state_reason"),
                "blocked_reason": daily_loss_accounting.get("risk_state_blocked_reason"),
                "updated_at": daily_loss_accounting.get("risk_state_updated_at"),
                "version": daily_loss_accounting.get("risk_state_version"),
                "bootstrapped": daily_loss_accounting.get("risk_state_bootstrapped"),
                "read_reason": daily_loss_accounting.get("risk_state_read_reason"),
                "pending_reservation_count": daily_loss_accounting.get(
                    "pending_reservation_count"
                ),
                "pending_reservation_ids": daily_loss_accounting.get("pending_reservation_ids"),
            },
            "live_risk_refresh": admission_daily_loss_accounting.get("risk_refresh")
            or daily_loss_accounting.get("risk_refresh"),
            "selected_decision": dict(selected_decision or {}),
            "selected_decisions": [
                dict(attempt.get("original_decision") or attempt.get("decision") or {})
                for attempt in live_attempts
            ],
            "selected_row": dict(selected_row or {}),
            "counts": {
                "collected_rows": int(collected_counts.get("rows") or 0),
                "decision_rows": int(collected_counts.get("decisions") or 0),
                "skip_rows": int(collected_counts.get("skips") or 0),
                "replay_trades": 1 if selected_trade else 0,
                "walk_forward_windows": 0,
                "live_attempts": len(live_attempts),
                "live_skipped": sum(
                    1 for attempt in live_attempts if attempt.get("status") == "skipped"
                ),
                "prior_live_attempts_reconciled": 0,
                "prior_reconciliation_rows_for_daily_loss": 0,
                "live_reconciliation_rows_for_daily_loss": len(
                    live_reconciliation.get("rows", [])
                ),
            },
            "report_summary": {
                "daily_loss_live_risk_day": daily_loss_accounting["live_risk_day"],
                "daily_loss_used_dollars": daily_loss_accounting["daily_loss_used_dollars"],
                "live_reconciliation_scope": "current_attempt_compact",
                "live_full_history_net_pnl_dollars": None,
                "live_full_history_unsettled_exposure_dollars": None,
                "live_daily_net_pnl_dollars": live_reconciliation["pnl"]["net_pnl_dollars"],
                "live_daily_unsettled_exposure_dollars": live_reconciliation["pnl"][
                    "unsettled_exposure_dollars"
                ],
                "live_settlement_status": live_reconciliation["settlement"]["status"],
                "live_attempt_skip_reasons": summarize_attempt_reasons(live_attempts),
            },
            "timing": timer.snapshot(
                quote_seen_at=parse_datetime(latest_attempt.get("quote_seen_at")),
                order_submit_at=parse_datetime(latest_attempt.get("order_submit_at")),
            ),
            "artifacts": artifact_records(artifacts),
        }
        if materialize_status:
            with timer.phase("status_materialization"):
                materialize_live_run_status(
                    settings=self._settings or settings_from_env(),
                    manifest=manifest,
                    live_attempts_payload=attempts_payload,
                    live_reconciliation=live_reconciliation,
                    require_postgres=require_postgres,
                )
            manifest["runtime_controls"]["live_status_materialized"] = True
        manifest["timing"] = timer.snapshot(
            quote_seen_at=parse_datetime(latest_attempt.get("quote_seen_at")),
            order_submit_at=parse_datetime(latest_attempt.get("order_submit_at")),
        )
        if self.config.decision_policy == "fair_value":
            manifest["live_edge_attribution"] = build_live_edge_attribution(
                decision=selected_decision,
                source_row=selected_row,
                config=self.config.as_dict(),
                runtime_config=runtime_config,
                runtime_controls=manifest["runtime_controls"],
                freshness=latest_freshness,
                timing=manifest["timing"],
            )
        write_json(run_dir / "manifest.json", manifest)
        manifest["artifacts"]["manifest"] = artifact_record(run_dir / "manifest.json")
        if self.config.s3_prefix:
            with timer.phase("s3_upload"):
                manifest["s3_uploads"] = upload_artifacts_to_s3(
                    manifest["artifacts"],
                    s3_prefix=self.config.s3_prefix,
                )
            manifest["timing"] = timer.snapshot(
                quote_seen_at=parse_datetime(latest_attempt.get("quote_seen_at")),
                order_submit_at=parse_datetime(latest_attempt.get("order_submit_at")),
            )
            write_json(run_dir / "manifest.json", manifest)
            manifest["artifacts"]["manifest"] = artifact_record(run_dir / "manifest.json")
        return manifest

    def _submit_live_attempts(
        self,
        *,
        replay_decisions: Sequence[Mapping[str, Any]],
        settings: Settings,
        run_id: str,
        generated_at: datetime,
        starting_daily_loss_used: float,
        daily_loss_accounting: Mapping[str, Any],
        market_exposure_by_ticker: Mapping[str, float],
        live_run_lock: "LiveRunLock",
    ) -> list[dict[str, Any]]:
        attempts: list[dict[str, Any]] = []
        daily_loss_used = starting_daily_loss_used
        market_exposure = dict(market_exposure_by_ticker)
        guard = evaluate_runtime_guard(settings)
        for index, order in enumerate(replay_decisions):
            market_ticker = str(order.get("ticker") or order.get("market_ticker") or "")
            if order.get("decision") != "trade":
                reason = str(order.get("reason") or "no_trade")
                attempts.append(
                    {
                        "attempt_id": f"fv_live_order_{uuid4().hex[:12]}",
                        "run_id": run_id,
                        "submitted_at": generated_at.isoformat(),
                        "market_ticker": market_ticker,
                        "side": order.get("side"),
                        "decision": dict(order),
                        "original_decision": dict(order),
                        "request_payload": {},
                        "max_loss_dollars": 0.0,
                        "daily_loss_used_before_dollars": round(daily_loss_used, 6),
                        "daily_loss_accounting": dict(daily_loss_accounting),
                        "market_exposure": {
                            "market_ticker": market_ticker,
                            "max_ticker_exposure_dollars": self.config.max_ticker_exposure_dollars,
                            "used_before_dollars": round(
                                float(market_exposure.get(market_ticker, 0.0)),
                                6,
                            ),
                            "remaining_before_dollars": round(
                                max(
                                    0.0,
                                    self.config.max_ticker_exposure_dollars
                                    - float(market_exposure.get(market_ticker, 0.0)),
                                ),
                                6,
                            ),
                            "intended_contracts": 0,
                            "sized_contracts": 0,
                        },
                        "runtime_guard": guard.as_dict(),
                        "live_run_lock": live_run_lock.as_dict(),
                        "attempt_index": index,
                        "status": "skipped",
                        "reason": reason,
                    }
                )
                continue
            current_market_exposure = float(market_exposure.get(market_ticker, 0.0))
            market_remaining = max(
                0.0,
                self.config.max_ticker_exposure_dollars - current_market_exposure,
            )
            sized_order = order_sized_to_market_cap(
                order,
                remaining_ticker_exposure_dollars=market_remaining,
            )
            request_payload = (
                live_order_request(sized_order, run_id=run_id) if sized_order is not None else {}
            )
            max_loss = float(sized_order.get("max_loss_dollars") or 0.0) if sized_order else 0.0
            market_exposure_state = {
                "market_ticker": market_ticker,
                "max_ticker_exposure_dollars": self.config.max_ticker_exposure_dollars,
                "used_before_dollars": round(current_market_exposure, 6),
                "remaining_before_dollars": round(market_remaining, 6),
                "intended_contracts": int(
                    order.get("intended_contracts") or order.get("contracts") or 0
                ),
                "sized_contracts": int(
                    sized_order.get("intended_contracts") or sized_order.get("contracts") or 0
                )
                if sized_order
                else 0,
            }
            base = {
                "attempt_id": f"fv_live_order_{uuid4().hex[:12]}",
                "run_id": run_id,
                "submitted_at": generated_at.isoformat(),
                "market_ticker": market_ticker,
                "side": order.get("side"),
                "decision": dict(sized_order) if sized_order else dict(order),
                "original_decision": dict(order),
                "request_payload": request_payload,
                "max_loss_dollars": round(max_loss, 6),
                "daily_loss_used_before_dollars": round(daily_loss_used, 6),
                "daily_loss_accounting": dict(daily_loss_accounting),
                "market_exposure": market_exposure_state,
                "runtime_guard": guard.as_dict(),
                "live_run_lock": live_run_lock.as_dict(),
                "attempt_index": index,
            }
            if live_run_lock.backend == "postgres":
                base["live_decision_authority_lease"] = live_run_lock.as_dict()
            if sized_order is None:
                attempts.append(
                    {**base, "status": "skipped", "reason": "market_exposure_cap_reached"}
                )
                continue
            if not live_run_lock.acquired:
                attempts.append(
                    {
                        **base,
                        "status": "skipped",
                        "reason": live_run_lock.reason or "live_run_lock_held",
                    }
                )
                continue
            if not self.config.submit_live_orders:
                attempts.append({**base, "status": "skipped", "reason": "submit_live_orders_false"})
                continue
            if not guard.can_submit_live_orders:
                attempts.append({**base, "status": "skipped", "reason": guard.denial_reason})
                continue
            if daily_loss_used + max_loss > self.config.max_daily_loss_dollars:
                attempts.append({**base, "status": "skipped", "reason": "daily_loss_cap_reached"})
                continue
            try:
                response = self.order_client.create_order(
                    request_payload=request_payload,
                    settings=settings,
                )
            except Exception as exc:
                attempts.append(
                    {
                        **base,
                        "status": "error",
                        "reason": f"live_order_error:{type(exc).__name__}",
                        "response_payload": {"message": str(exc)},
                    }
                )
                continue
            fill_count = int(numeric_response_value(response, ("fill_count", "fill_count_fp")) or 0)
            accepted = exchange_response_accepted(response)
            attempt = {
                **base,
                "status": "submitted" if accepted else "rejected",
                "reason": "submitted" if accepted else "exchange_rejected",
                "response_payload": dict(response),
                "order_id": response.get("order_id"),
                "client_order_id": response.get("client_order_id")
                or request_payload.get("client_order_id"),
                "fill_count": fill_count,
                "remaining_count": numeric_response_value(
                    response,
                    ("remaining_count", "remaining_count_fp"),
                ),
            }
            attempts.append(attempt)
            if fill_count > 0:
                filled_max_loss = filled_max_loss_estimate(sized_order, fill_count)
                daily_loss_used += filled_max_loss
                market_exposure[market_ticker] = (
                    float(market_exposure.get(market_ticker, 0.0)) + filled_max_loss
                )
        return attempts


class PhaseTimer:
    def __init__(self) -> None:
        self.started_at = time.perf_counter()
        self.phase_seconds: dict[str, float] = {}
        self.order_submit_at: datetime | None = None

    @contextmanager
    def phase(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.phase_seconds[name] = round(
                self.phase_seconds.get(name, 0.0) + time.perf_counter() - started,
                6,
            )

    def ensure_phases(self, *names: str) -> None:
        for name in names:
            self.phase_seconds.setdefault(name, 0.0)

    def snapshot(
        self,
        *,
        quote_seen_at: datetime | None = None,
        order_submit_at: datetime | None = None,
    ) -> dict[str, Any]:
        submit_at = order_submit_at or self.order_submit_at
        quote_to_submit = (
            round((submit_at - quote_seen_at).total_seconds(), 6)
            if quote_seen_at is not None and submit_at is not None
            else None
        )
        return {
            "total_elapsed_seconds": round(time.perf_counter() - self.started_at, 6),
            "phase_seconds": dict(sorted(self.phase_seconds.items())),
            "quote_seen_at": quote_seen_at.isoformat() if quote_seen_at else None,
            "order_submit_at": submit_at.isoformat() if submit_at else None,
            "quote_to_submit_seconds": quote_to_submit,
        }


def runtime_config_snapshot(
    config: FairValueLiveTradingJobConfig,
    *,
    reason: str = "live_run_lock_held",
) -> dict[str, Any]:
    source = (
        "not_read_authority_denied"
        if reason.startswith("live_decision_authority_")
        else "not_read_lock_held"
    )
    return {
        "source": source,
        "not_read_reason": reason,
        "strategy": config.strategy,
        "config_id": None,
        "version": None,
        "snapshot": {
            "strategy": config.strategy,
            "decision_policy": config.decision_policy,
            "max_order_dollars": config.max_order_dollars,
            "max_market_exposure_dollars": config.max_ticker_exposure_dollars,
            "max_daily_loss_dollars": config.max_daily_loss_dollars,
            "min_edge": config.min_edge,
            "min_contract_price": config.min_contract_price,
            "max_markets": config.max_markets,
            "market_context_source": config.market_context_source,
            "brti_future_tolerance_seconds": config.brti_future_tolerance_seconds,
        },
    }


def settings_with_materialized_private_key(
    settings: Settings | None,
) -> tuple[Settings, dict[str, Any]]:
    materialization: dict[str, Any] = {
        "private_key_pem_present": bool(os.environ.get("KALSHI_PRIVATE_KEY_PEM")),
        "private_key_path_materialized": False,
        "credential_error": None,
    }
    if settings is not None and settings.kalshi_private_key_path:
        return settings, materialization
    try:
        materialized_path = materialize_private_key_from_env()
    except Exception as exc:
        materialization["credential_error"] = "invalid_kalshi_credentials"
        materialization["error_type"] = type(exc).__name__
        return settings or settings_from_env(), materialization
    effective = settings or settings_from_env()
    if materialized_path is not None and not effective.kalshi_private_key_path:
        effective = replace(effective, kalshi_private_key_path=str(materialized_path))
        materialization["private_key_path_materialized"] = True
    return effective, materialization


def runtime_guard_with_credential_materialization(
    *,
    settings: Settings,
    credential_materialization: Mapping[str, Any],
):
    guard = evaluate_runtime_guard(settings)
    if (
        credential_materialization.get("credential_error")
        and guard.runtime_mode.value == "gated-live"
        and settings.enable_live_orders
    ):
        return replace(
            guard,
            live_enabled=False,
            can_submit_live_orders=False,
            denial_reason=str(credential_materialization["credential_error"]),
            credentials_present=False,
        )
    return guard


def lock_held_attempt(
    *,
    run_id: str,
    generated_at: datetime,
    live_run_lock: "LiveRunLock",
    strategy: str = FAIR_VALUE_LIVE_STRATEGY,
) -> dict[str, Any]:
    reason = live_run_lock.reason or "live_run_lock_held"
    attempt = {
        "attempt_id": f"{live_run_id_prefix(strategy)}_order_{uuid4().hex[:12]}",
        "run_id": run_id,
        "strategy": strategy,
        "submitted_at": generated_at.isoformat(),
        "market_ticker": "",
        "side": None,
        "decision": {"decision": "skip", "reason": reason},
        "original_decision": {"decision": "skip", "reason": reason},
        "request_payload": {},
        "max_loss_dollars": 0.0,
        "daily_loss_used_before_dollars": 0.0,
        "daily_loss_accounting": {},
        "market_exposure": {},
        "runtime_guard": {},
        "live_run_lock": live_run_lock.as_dict(),
        "attempt_index": 0,
        "status": "skipped",
        "reason": reason,
    }
    if live_run_lock.backend == "postgres":
        attempt["live_decision_authority_lease"] = live_run_lock.as_dict()
    return attempt


def live_run_id_prefix(strategy: str) -> str:
    if strategy == EXPENSIVE_YES_LIVE_STRATEGY:
        return "expensive_yes_live"
    return "fv_live"


def live_attempt_with_edge_attribution(
    attempt: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    runtime_controls: Mapping[str, Any],
    timing: Mapping[str, Any],
    decision_policy: LiveDecisionPolicy,
) -> dict[str, Any]:
    payload = dict(attempt)
    if decision_policy != "fair_value":
        return payload
    freshness = as_mapping(payload.get("freshness"))
    payload["live_edge_attribution"] = build_live_edge_attribution(
        decision=as_mapping(payload.get("original_decision"))
        or as_mapping(payload.get("decision")),
        source_row=as_mapping(payload.get("source_row")),
        config=config,
        runtime_config=runtime_config,
        runtime_controls=runtime_controls,
        freshness=freshness,
        timing=timing,
    )
    return payload


def live_decision_rows_with_candidate_attribution(
    collected: Mapping[str, Any] | None,
    *,
    config: Mapping[str, Any],
    runtime_config: Mapping[str, Any],
    runtime_controls: Mapping[str, Any],
    generated_at: datetime,
    timing: Mapping[str, Any],
    decision_policy: LiveDecisionPolicy,
    replay_config: FairValueReplayConfig,
) -> dict[str, Any] | None:
    if collected is None:
        return None
    payload = dict(collected)
    rows = [
        dict(row)
        for row in as_sequence(payload.get("rows"))
        if isinstance(row, Mapping)
    ]
    if decision_policy != "fair_value":
        payload["rows"] = rows
        return payload

    attributed_rows: list[dict[str, Any]] = []
    candidate_count = 0
    for row in rows:
        if row.get("row_type") != "decision":
            attributed_rows.append(row)
            continue
        candidate_count += 1
        decision = candidate_attribution_decision(row, config=replay_config)
        freshness = live_decision_freshness(row, generated_at=generated_at)
        attributed_rows.append(
            {
                **row,
                "live_edge_attribution": build_live_edge_attribution(
                    decision=decision,
                    source_row=row,
                    config=config,
                    runtime_config=runtime_config,
                    runtime_controls=runtime_controls,
                    freshness=freshness,
                    timing=timing,
                ),
            }
        )
    payload["rows"] = attributed_rows
    payload["candidate_live_edge_attribution_count"] = candidate_count
    return payload


def candidate_attribution_decision(
    row: Mapping[str, Any],
    *,
    config: FairValueReplayConfig,
) -> dict[str, Any]:
    try:
        return decide_trade(row, config=config, cumulative_pnl=0.0)
    except Exception as exc:
        ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        return {
            "ticker": ticker,
            "market_ticker": ticker,
            "decision_timestamp": row.get("decision_timestamp"),
            "decision": "skip",
            "reason": f"candidate_attribution_error:{type(exc).__name__}",
        }


def live_market_context_evidence(
    row: Mapping[str, Any] | None,
    *,
    config: Mapping[str, Any],
    freshness: Mapping[str, Any],
) -> dict[str, Any]:
    source_row = as_mapping(row)
    source = (
        source_row.get("market_context_source")
        or config.get("market_context_source")
        or MARKET_CONTEXT_COINBASE_PRIMARY
    )
    return {
        "market_context_source": source,
        "market_context_status": source_row.get("market_context_status"),
        "external_close_source": source_row.get("external_close_source"),
        "external_close_from_brti": (
            source_row.get("external_close_source") == "brti_latest_context"
        ),
        "external_close": source_row.get("external_close"),
        "brti": {
            "index_id": source_row.get("brti_index_id"),
            "context_status": source_row.get("brti_context_status"),
            "context_reason": source_row.get("brti_context_reason"),
            "source_timestamp": source_row.get("brti_source_timestamp"),
            "received_at": source_row.get("brti_received_at"),
            "context_age_seconds": source_row.get("brti_context_age_seconds"),
            "freshness_limit_seconds": source_row.get("brti_freshness_limit_seconds"),
            "source_ahead_seconds": source_row.get("brti_source_ahead_seconds"),
            "future_tolerance_seconds": source_row.get("brti_future_tolerance_seconds"),
            "future_tolerance_applied": source_row.get(
                "brti_future_tolerance_applied"
            ),
            "source_lag_ms": source_row.get("brti_source_lag_ms"),
            "raw_event_id": source_row.get("brti_raw_event_id"),
            "payload_hash": source_row.get("brti_payload_hash"),
        },
        "coinbase_diagnostics": {
            "status": source_row.get("coinbase_diagnostic_status"),
            "product_id": source_row.get("coinbase_product_id"),
            "max_source_event_timestamp": source_row.get(
                "coinbase_max_source_event_timestamp"
            ),
            "source_lag_ms": source_row.get("coinbase_source_lag_ms"),
            "basis_dollars": source_row.get("brti_coinbase_basis_dollars"),
            "basis_pct": source_row.get("brti_coinbase_basis_pct"),
        },
        "freshness": dict(freshness),
    }


def select_live_decision_pairs(
    rows: object,
    *,
    config: FairValueReplayConfig,
    decision_policy: LiveDecisionPolicy = "fair_value",
) -> list[tuple[dict[str, Any], Mapping[str, Any] | None]]:
    if decision_policy == "expensive_yes":
        return select_expensive_yes_live_decisions(rows, config=config)
    decision, row = select_one_cycle_live_decision(rows, config=config)
    return [(decision, row)]


def select_one_cycle_live_decision(
    rows: object,
    *,
    config: FairValueReplayConfig,
) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    row_list = [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    decisions: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    for row in sorted(
        [row for row in row_list if row.get("row_type") == "decision"],
        key=replay_sort_key,
    ):
        decisions.append((decide_trade(row, config=config, cumulative_pnl=0.0), row))
    trades = [
        (decision, row) for decision, row in decisions if decision.get("decision") == "trade"
    ]
    if trades:
        return max(
            trades,
            key=lambda item: (
                float(item[0].get("edge") or 0.0),
                str(item[0].get("ticker") or ""),
            ),
        )
    if decisions:
        return decisions[0]
    skips = sorted(
        [row for row in row_list if row.get("row_type") == "skip"],
        key=replay_sort_key,
    )
    if skips:
        row = skips[0]
        return (
            {
                "ticker": str(row.get("ticker") or row.get("market_ticker") or ""),
                "market_ticker": str(row.get("ticker") or row.get("market_ticker") or ""),
                "decision_timestamp": row.get("decision_timestamp"),
                "decision": "skip",
                "reason": str(row.get("skip_reason") or "collector_skip"),
            },
            row,
        )
    return (
        {
            "ticker": "",
            "market_ticker": "",
            "decision_timestamp": None,
            "decision": "skip",
            "reason": "no_current_market",
        },
        None,
    )


def select_expensive_yes_live_decisions(
    rows: object,
    *,
    config: FairValueReplayConfig,
) -> list[tuple[dict[str, Any], Mapping[str, Any] | None]]:
    row_list = [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    decisions: list[tuple[dict[str, Any], Mapping[str, Any] | None]] = []
    eligible_rows = sorted(
        [row for row in row_list if row.get("row_type") == "decision"],
        key=replay_sort_key,
    )
    for row in eligible_rows:
        decisions.append((expensive_yes_decision(row, config=config), row))
    for row in sorted(
        [row for row in row_list if row.get("row_type") == "skip"],
        key=replay_sort_key,
    ):
        decisions.append(
            (
                {
                    "ticker": str(row.get("ticker") or row.get("market_ticker") or ""),
                    "market_ticker": str(row.get("ticker") or row.get("market_ticker") or ""),
                    "decision_timestamp": row.get("decision_timestamp"),
                    "decision": "skip",
                    "reason": str(row.get("skip_reason") or "collector_skip"),
                    "decision_policy": "expensive_yes",
                },
                row,
            )
        )
    if decisions:
        return decisions
    return [
        (
            {
                "ticker": "",
                "market_ticker": "",
                "decision_timestamp": None,
                "decision": "skip",
                "reason": "no_current_market",
                "decision_policy": "expensive_yes",
            },
            None,
        )
    ]


def expensive_yes_decision(
    row: Mapping[str, Any],
    *,
    config: FairValueReplayConfig,
) -> dict[str, Any]:
    ticker = str(row.get("ticker") or row.get("market_ticker") or "")
    yes_ask = optional_float(row.get("yes_ask"))
    threshold = float(config.min_contract_price)
    base = {
        "ticker": ticker,
        "market_ticker": ticker,
        "decision_timestamp": row.get("decision_timestamp"),
        "decision_policy": "expensive_yes",
        "side": "yes",
        "observed_yes_ask": yes_ask,
        "yes_ask_threshold": threshold,
    }
    if not ticker:
        return {**base, "decision": "skip", "reason": "malformed_market"}
    if yes_ask is None:
        return {**base, "decision": "skip", "reason": "missing_yes_ask"}
    if yes_ask < threshold:
        return {**base, "decision": "skip", "reason": "yes_ask_below_threshold"}
    fee_per_contract = taker_fee(yes_ask, config.taker_fee_multiplier)
    max_loss_per_contract = yes_ask + fee_per_contract
    if max_loss_per_contract <= 0:
        return {**base, "decision": "skip", "reason": "sizing_impossible"}
    intended_contracts = int(config.max_order_dollars // max_loss_per_contract)
    if intended_contracts < 1:
        return {**base, "decision": "skip", "reason": "sizing_impossible"}
    cost = yes_ask * intended_contracts
    fees = fee_per_contract * intended_contracts
    max_loss = cost + fees
    if max_loss > config.max_loss_dollars:
        allowed_contracts = int(config.max_loss_dollars // max_loss_per_contract)
        if allowed_contracts < 1:
            return {**base, "decision": "skip", "reason": "sizing_impossible"}
        intended_contracts = allowed_contracts
        cost = yes_ask * intended_contracts
        fees = fee_per_contract * intended_contracts
        max_loss = cost + fees
    return {
        **base,
        "decision": "trade",
        "reason": "yes_ask_at_or_above_threshold",
        "price": round(yes_ask, 6),
        "yes_ask": round(yes_ask, 6),
        "fee_per_contract": round(fee_per_contract, 6),
        "intended_contracts": intended_contracts,
        "contracts": intended_contracts,
        "cost_dollars": round(cost, 6),
        "fees_dollars": round(fees, 6),
        "payout_dollars": 0.0,
        "pnl_dollars": 0.0,
        "max_loss_dollars": round(max_loss, 6),
    }


def apply_live_freshness_gates(
    decision: Mapping[str, Any],
    row: Mapping[str, Any] | None,
    *,
    generated_at: datetime,
    quote_stale_seconds: int,
    coinbase_feature_stale_seconds: int,
    require_coinbase_freshness: bool = True,
) -> dict[str, Any]:
    result = dict(decision)
    if result.get("decision") != "trade":
        return result
    freshness = live_decision_freshness(row, generated_at=generated_at)
    quote_age = freshness.get("quote_age_seconds")
    if quote_age is None or float(quote_age) > quote_stale_seconds:
        return {**result, "decision": "skip", "reason": "quote_stale"}
    if require_coinbase_freshness:
        coinbase_age = freshness.get("coinbase_feature_age_seconds")
        if coinbase_age is None or float(coinbase_age) > coinbase_feature_stale_seconds:
            return {**result, "decision": "skip", "reason": "coinbase_context_stale"}
    return result


def live_decision_freshness(
    row: Mapping[str, Any] | None,
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    if not row:
        return {
            "quote_seen_at": None,
            "quote_age_seconds": None,
            "market_context_source": None,
            "external_close_source": None,
            "coinbase_max_source_event_timestamp": None,
            "coinbase_feature_age_seconds": None,
            "brti_source_timestamp": None,
            "brti_context_age_seconds": None,
            "brti_context_status": None,
            "brti_freshness_limit_seconds": None,
            "brti_source_ahead_seconds": None,
            "brti_future_tolerance_seconds": None,
            "brti_future_tolerance_applied": None,
        }
    quote_seen_at = parse_datetime(
        row.get("quote_observed_at") or row.get("kalshi_received_at") or row.get("decision_timestamp")
    )
    coinbase_seen_at = parse_datetime(row.get("coinbase_max_source_event_timestamp"))
    brti_seen_at = parse_datetime(row.get("brti_source_timestamp"))
    quote_age = (
        max(0.0, (generated_at - quote_seen_at).total_seconds())
        if quote_seen_at is not None
        else None
    )
    coinbase_age = (
        max(0.0, (generated_at - coinbase_seen_at).total_seconds())
        if coinbase_seen_at is not None
        else None
    )
    if coinbase_age is None and row.get("coinbase_source_lag_ms") is not None:
        coinbase_age = max(0.0, float(row.get("coinbase_source_lag_ms") or 0.0) / 1000.0)
    brti_age = (
        max(0.0, (generated_at - brti_seen_at).total_seconds())
        if brti_seen_at is not None
        else optional_float(row.get("brti_context_age_seconds"))
    )
    return {
        "quote_seen_at": quote_seen_at.isoformat() if quote_seen_at else None,
        "quote_age_seconds": round(quote_age, 6) if quote_age is not None else None,
        "market_context_source": row.get("market_context_source"),
        "external_close_source": row.get("external_close_source"),
        "coinbase_max_source_event_timestamp": coinbase_seen_at.isoformat()
        if coinbase_seen_at
        else None,
        "coinbase_feature_age_seconds": round(coinbase_age, 6)
        if coinbase_age is not None
        else None,
        "brti_source_timestamp": brti_seen_at.isoformat() if brti_seen_at else None,
        "brti_context_age_seconds": round(brti_age, 6) if brti_age is not None else None,
        "brti_context_status": row.get("brti_context_status"),
        "brti_freshness_limit_seconds": row.get("brti_freshness_limit_seconds"),
        "brti_source_ahead_seconds": row.get("brti_source_ahead_seconds"),
        "brti_future_tolerance_seconds": row.get("brti_future_tolerance_seconds"),
        "brti_future_tolerance_applied": row.get("brti_future_tolerance_applied"),
    }


def live_risk_state_for_day(
    *,
    settings: Settings,
    strategy: str,
    live_risk_day: date,
    apply_migrations: bool = True,
) -> LiveRiskAdmissionState | None:
    try:
        return LiveRiskAdmissionRepository(settings.database_url).get_state(
            strategy=strategy,
            live_risk_day=live_risk_day,
            apply_migrations=apply_migrations,
        )
    except Exception:
        return None


def live_risk_state_for_admission(
    *,
    settings: Settings,
    strategy: str,
    live_risk_day: date,
    generated_at: datetime,
    run_id: str,
) -> tuple[LiveRiskAdmissionState | None, dict[str, Any]]:
    repository = LiveRiskAdmissionRepository(settings.database_url)
    try:
        state = repository.get_state(strategy=strategy, live_risk_day=live_risk_day)
    except Exception as exc:
        return None, {
            "risk_state_bootstrapped": False,
            "risk_state_read_reason": "risk_state_unavailable",
            "risk_state_error_type": type(exc).__name__,
        }
    if state is not None:
        return state, {
            "risk_state_bootstrapped": False,
            "risk_state_read_reason": "existing_current_live_risk_day",
        }
    try:
        state, created = repository.create_zero_state_if_missing(
            strategy=strategy,
            live_risk_day=live_risk_day,
            updated_at=generated_at,
            metadata={
                "bootstrap_reason": "missing_current_live_risk_day",
                "bootstrap_run_id": run_id,
                "full_reconciliation_performed": False,
            },
        )
    except Exception as exc:
        return None, {
            "risk_state_bootstrapped": False,
            "risk_state_read_reason": "risk_state_unavailable",
            "risk_state_error_type": type(exc).__name__,
        }
    return state, {
        "risk_state_bootstrapped": created,
        "risk_state_read_reason": "bootstrapped_missing_current_live_risk_day"
        if created
        else "existing_current_live_risk_day",
    }


def live_risk_accounting_report(
    state: LiveRiskAdmissionState | None,
    *,
    generated_at: datetime,
    live_risk_timezone: str,
    stale_after_seconds: int = DEFAULT_LIVE_RISK_STALE_SECONDS,
) -> dict[str, Any]:
    live_risk_day, window_start_utc, window_end_utc = live_risk_window(
        generated_at=generated_at,
        live_risk_timezone=live_risk_timezone,
    )
    if state is None:
        return {
            **empty_live_risk_accounting(
                generated_at=generated_at,
                live_risk_timezone=live_risk_timezone,
                reason="risk_state_missing",
            ),
            "basis": "live_risk_admission_state",
        }
    invalid_reason = state_denial_reason(
        state,
        now=generated_at,
        stale_after_seconds=stale_after_seconds,
    )
    state_payload = state.as_dict()
    return {
        "schema_version": FAIR_VALUE_LIVE_DAILY_LOSS_ACCOUNTING_SCHEMA,
        "basis": "live_risk_admission_state",
        "timezone": live_risk_timezone,
        "live_risk_day": live_risk_day.isoformat(),
        "window_start_utc": window_start_utc.isoformat(),
        "window_end_utc": window_end_utc.isoformat(),
        "risk_state_status": state.status,
        "risk_state_reason": invalid_reason,
        "risk_state_blocked_reason": state_payload.get("blocked_reason"),
        "risk_state_updated_at": state.updated_at.isoformat(),
        "risk_state_version": state.version,
        "prior_reconciliation_rows": 0,
        "same_live_risk_day_rows": 0,
        "same_live_risk_day_filled_rows": 0,
        "same_live_risk_day_no_fill_rows": 0,
        "same_live_risk_day_settled_rows": 0,
        "same_live_risk_day_unsettled_rows": 0,
        "daily_loss_realized_dollars": round(state.daily_loss_used_dollars, 6),
        "open_exposure_dollars": round(state.open_exposure_dollars, 6),
        "pending_exposure_dollars": round(state.pending_exposure_dollars, 6),
        "pending_reservation_count": len(state.pending_reservations),
        "pending_reservation_ids": sorted(state.pending_reservations),
        "daily_loss_used_dollars": round(state.daily_loss_used_dollars, 6),
        "per_market_exposure_dollars": dict(state.per_market_exposure_dollars),
    }


def empty_live_risk_accounting(
    *,
    generated_at: datetime,
    live_risk_timezone: str,
    reason: str,
) -> dict[str, Any]:
    live_risk_day, window_start_utc, window_end_utc = live_risk_window(
        generated_at=generated_at,
        live_risk_timezone=live_risk_timezone,
    )
    return {
        "schema_version": FAIR_VALUE_LIVE_DAILY_LOSS_ACCOUNTING_SCHEMA,
        "basis": "live_risk_admission_state",
        "timezone": live_risk_timezone,
        "live_risk_day": live_risk_day.isoformat(),
        "window_start_utc": window_start_utc.isoformat(),
        "window_end_utc": window_end_utc.isoformat(),
        "risk_state_status": "missing",
        "risk_state_reason": reason,
        "risk_state_blocked_reason": None,
        "prior_reconciliation_rows": 0,
        "same_live_risk_day_rows": 0,
        "same_live_risk_day_filled_rows": 0,
        "same_live_risk_day_no_fill_rows": 0,
        "same_live_risk_day_settled_rows": 0,
        "same_live_risk_day_unsettled_rows": 0,
        "daily_loss_realized_dollars": 0.0,
        "open_exposure_dollars": 0.0,
        "pending_exposure_dollars": 0.0,
        "pending_reservation_count": 0,
        "pending_reservation_ids": [],
        "daily_loss_used_dollars": 0.0,
        "per_market_exposure_dollars": {},
    }


def compact_live_reconciliation(
    attempts: Sequence[Mapping[str, Any]],
    *,
    generated_at: datetime,
    max_ticker_exposure_dollars: float,
) -> dict[str, Any]:
    rows = [compact_reconciliation_row(attempt, generated_at=generated_at) for attempt in attempts]
    filled = [row for row in rows if int(row["filled_contracts"]) > 0]
    unsettled = [row for row in filled if row["settlement_status"] == "unsettled"]
    pnl = {
        "net_pnl_dollars": 0.0,
        "gross_cost_dollars": round(sum(float(row["cost_dollars"]) for row in filled), 6),
        "fees_dollars": round(sum(float(row["fees_dollars"]) for row in filled), 6),
        "payout_dollars": 0.0,
        "unsettled_exposure_dollars": round(
            sum(float(row["max_loss_dollars"]) for row in unsettled),
            6,
        ),
        "filled_contracts": sum(int(row["filled_contracts"]) for row in filled),
        "settled_trade_count": 0,
        "unsettled_trade_count": len(unsettled),
    }
    return {
        "schema_version": FAIR_VALUE_LIVE_RECONCILIATION_SCHEMA,
        "generated_at": generated_at.isoformat(),
        "scope": "current_attempt_compact",
        "counts": {
            "attempts": len(rows),
            "submitted": sum(1 for row in rows if row["order_status"] == "submitted"),
            "filled": len(filled),
            "settled": 0,
            "unsettled": len(unsettled),
            "no_fill": sum(1 for row in rows if row["settlement_status"] == "no_fill"),
            "skipped_or_error": sum(
                1 for row in rows if row["order_status"] in {"skipped", "error", "rejected"}
            ),
        },
        "pnl": pnl,
        "settlement": {
            "status": "unreconciled" if unsettled else "reconciled",
            "default_reporting": "current_attempt_compact_no_public_settlement_lookup",
            "settled_rows": 0,
            "unsettled_rows": len(unsettled),
            "unsettled_exposure_dollars": pnl["unsettled_exposure_dollars"],
        },
        "per_market_exposure": per_market_exposure_report(
            rows,
            max_ticker_exposure_dollars=max_ticker_exposure_dollars,
        ),
        "rows": rows,
    }


def compact_reconciliation_row(
    attempt: Mapping[str, Any],
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    decision = as_mapping(attempt.get("decision"))
    response = as_mapping(attempt.get("response_payload"))
    filled_contracts = int(
        numeric_response_value(response, ("fill_count_fp", "fill_count", "filled_quantity"))
        or attempt.get("fill_count")
        or 0
    )
    price = float(decision.get("price") or 0.0)
    fee_per_contract = float(decision.get("fee_per_contract") or taker_fee(price, 0.07))
    cost = round(price * filled_contracts, 6)
    fees = round(fee_per_contract * filled_contracts, 6)
    if filled_contracts <= 0:
        settlement = "no_fill"
    else:
        settlement = "unsettled"
    return {
        "attempt_id": attempt.get("attempt_id"),
        "run_id": attempt.get("run_id"),
        "submitted_at": attempt.get("submitted_at"),
        "reconciled_at": generated_at.isoformat(),
        "market_ticker": str(attempt.get("market_ticker") or decision.get("ticker") or ""),
        "side": str(attempt.get("side") or decision.get("side") or ""),
        "order_status": attempt.get("status"),
        "order_id": attempt.get("order_id") or response.get("order_id"),
        "client_order_id": attempt.get("client_order_id") or response.get("client_order_id"),
        "filled_contracts": filled_contracts,
        "cost_dollars": cost,
        "fees_dollars": fees,
        "payout_dollars": 0.0,
        "pnl_dollars": 0.0,
        "max_loss_dollars": round(cost + fees, 6),
        "settlement_status": settlement,
        "market_status": None,
        "result": None,
        "order_detail_observed": False,
        "order_detail_error": None,
    }


@dataclass
class LiveRunLock:
    backend: str
    acquired: bool
    token: str
    strategy: str = FAIR_VALUE_LIVE_STRATEGY
    run_id: str | None = None
    reason: str | None = None
    path: Path | None = None
    bucket: str | None = None
    key: str | None = None
    existing: Mapping[str, Any] | None = None
    client: Any = None
    owner_id: str | None = None
    fencing_token: int | None = None
    lease_status: str | None = None
    acquired_at: datetime | None = None
    expires_at: datetime | None = None
    released_at: datetime | None = None
    authority_repository: LiveDecisionAuthorityLeaseRepository | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": LIVE_DECISION_AUTHORITY_LEASE_SCHEMA
            if self.backend == "postgres"
            else FAIR_VALUE_LIVE_LOCK_SCHEMA,
            "backend": self.backend,
            "acquired": self.acquired,
            "token": self.token,
            "strategy": self.strategy,
            "reason": self.reason,
        }
        if self.owner_id is not None:
            payload["owner_id"] = self.owner_id
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.fencing_token is not None:
            payload["fencing_token"] = self.fencing_token
        if self.lease_status is not None:
            payload["status"] = self.lease_status
        if self.acquired_at is not None:
            payload["acquired_at"] = self.acquired_at.isoformat()
        if self.expires_at is not None:
            payload["expires_at"] = self.expires_at.isoformat()
        if self.released_at is not None:
            payload["released_at"] = self.released_at.isoformat()
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.bucket is not None:
            payload["bucket"] = self.bucket
        if self.key is not None:
            payload["key"] = self.key
        if self.existing is not None:
            payload["existing"] = dict(self.existing)
        return payload

    def release(self) -> None:
        if not self.acquired:
            return
        if self.backend == "local" and self.path is not None:
            release_local_live_run_lock(self.path, token=self.token)
        if self.backend == "s3" and self.client is not None and self.bucket and self.key:
            release_s3_live_run_lock(
                self.client,
                bucket=self.bucket,
                key=self.key,
                token=self.token,
            )
        if (
            self.backend == "postgres"
            and self.authority_repository is not None
            and self.owner_id is not None
            and self.fencing_token is not None
        ):
            self.authority_repository.release(
                strategy=self.strategy,
                owner_id=self.owner_id,
                fencing_token=self.fencing_token,
            )


def should_materialize_live_run_status(live_run_lock: LiveRunLock) -> bool:
    if live_run_lock.backend == "postgres":
        return True
    return live_run_lock.acquired or live_run_lock.reason != "live_run_lock_held"


def acquire_live_run_lock(
    *,
    output_root: Path,
    s3_prefix: str | None,
    run_id: str,
    generated_at: datetime,
    enabled: bool,
    strategy: str = FAIR_VALUE_LIVE_STRATEGY,
    ttl_seconds: int = FAIR_VALUE_LIVE_LOCK_TTL_SECONDS,
    settings: Settings | None = None,
    use_postgres_authority: bool = False,
) -> LiveRunLock:
    if use_postgres_authority:
        return acquire_postgres_live_decision_authority(
            settings=settings or settings_from_env(),
            run_id=run_id,
            generated_at=generated_at,
            strategy=strategy,
            ttl_seconds=ttl_seconds,
        )
    if not enabled:
        return LiveRunLock(
            backend="none",
            acquired=True,
            token="",
            strategy=strategy,
            run_id=run_id,
            reason="submit_live_orders_false",
        )
    token = uuid4().hex
    payload = live_run_lock_payload(
        run_id=run_id,
        generated_at=generated_at,
        token=token,
        ttl_seconds=ttl_seconds,
    )
    if s3_prefix:
        return acquire_s3_live_run_lock(
            s3_prefix=s3_prefix,
            strategy=strategy,
            token=token,
            payload=payload,
            now=generated_at,
        )
    return acquire_local_live_run_lock(
        output_root=output_root,
        strategy=strategy,
        token=token,
        payload=payload,
        now=generated_at,
    )


def should_use_postgres_authority_lease(config: FairValueLiveTradingJobConfig) -> bool:
    return (
        not config.submit_live_orders
        and config.runtime_config_source == "postgres"
    )


def acquire_postgres_live_decision_authority(
    *,
    settings: Settings,
    run_id: str,
    generated_at: datetime,
    strategy: str = FAIR_VALUE_LIVE_STRATEGY,
    ttl_seconds: int = FAIR_VALUE_LIVE_LOCK_TTL_SECONDS,
) -> LiveRunLock:
    repository = LiveDecisionAuthorityLeaseRepository(settings.database_url)
    owner_id = f"{run_id}:{uuid4().hex[:12]}"
    try:
        result = repository.acquire(
            strategy=strategy,
            run_id=run_id,
            owner_id=owner_id,
            now=generated_at,
            ttl_seconds=ttl_seconds,
            metadata={
                "source": "fair_value_live_report_only",
                "submit_live_orders": False,
            },
        )
    except Exception as exc:
        return LiveRunLock(
            backend="postgres",
            acquired=False,
            token="",
            strategy=strategy,
            run_id=run_id,
            reason="live_decision_authority_unavailable",
            existing={
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
            owner_id=owner_id,
        )
    lease = result.lease or result.current_lease
    if result.acquired and lease is not None:
        return live_run_lock_from_authority_lease(
            lease,
            acquired=True,
            authority_repository=repository,
        )
    return LiveRunLock(
        backend="postgres",
        acquired=False,
        token=str(lease.fencing_token) if lease else "",
        strategy=strategy,
        run_id=lease.run_id if lease else run_id,
        reason=result.reason or "live_decision_authority_held",
        existing=lease.as_dict() if lease else None,
        owner_id=owner_id,
        authority_repository=repository,
    )


def live_run_lock_from_authority_lease(
    lease: LiveDecisionAuthorityLease,
    *,
    acquired: bool,
    authority_repository: LiveDecisionAuthorityLeaseRepository,
) -> LiveRunLock:
    return LiveRunLock(
        backend="postgres",
        acquired=acquired,
        token=str(lease.fencing_token),
        strategy=lease.strategy,
        run_id=lease.run_id,
        reason=None if acquired else "live_decision_authority_held",
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
        lease_status=lease.status,
        acquired_at=lease.acquired_at,
        expires_at=lease.expires_at,
        released_at=lease.released_at,
        authority_repository=authority_repository,
    )


def live_run_lock_payload(
    *,
    run_id: str,
    generated_at: datetime,
    token: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    acquired_at = ensure_utc(generated_at)
    return {
        "schema_version": FAIR_VALUE_LIVE_LOCK_SCHEMA,
        "run_id": run_id,
        "token": token,
        "acquired_at": acquired_at.isoformat(),
        "expires_at": (acquired_at + timedelta(seconds=ttl_seconds)).isoformat(),
    }


def acquire_local_live_run_lock(
    *,
    output_root: Path,
    strategy: str = FAIR_VALUE_LIVE_STRATEGY,
    token: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> LiveRunLock:
    path = output_root / f".{strategy}_run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            existing = read_json_file_or_empty(path)
            if live_run_lock_expired(existing, now=now):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            return LiveRunLock(
                backend="local",
                acquired=False,
                token=token,
                strategy=strategy,
                reason="live_run_lock_held",
                path=path,
                existing=existing,
            )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True)
        return LiveRunLock(
            backend="local",
            acquired=True,
            token=token,
            strategy=strategy,
            path=path,
        )
    return LiveRunLock(
        backend="local",
        acquired=False,
        token=token,
        strategy=strategy,
        reason="live_run_lock_held",
        path=path,
        existing=read_json_file_or_empty(path),
    )


def release_local_live_run_lock(path: Path, *, token: str) -> None:
    existing = read_json_file_or_empty(path)
    if existing and existing.get("token") != token:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def acquire_s3_live_run_lock(
    *,
    s3_prefix: str,
    strategy: str = FAIR_VALUE_LIVE_STRATEGY,
    token: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> LiveRunLock:
    bucket, prefix = parse_s3_prefix(s3_prefix)
    key = live_run_lock_s3_key(prefix, strategy=strategy)
    try:
        import boto3  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on AWS image environment
        raise RuntimeError("S3 live-run locking requires boto3") from exc
    client = boto3.client("s3")
    for _attempt in range(2):
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(dict(payload), sort_keys=True).encode("utf-8"),
                ContentType="application/json",
                IfNoneMatch="*",
            )
            return LiveRunLock(
                backend="s3",
                acquired=True,
                token=token,
                strategy=strategy,
                bucket=bucket,
                key=key,
                client=client,
            )
        except Exception as exc:
            if not s3_precondition_failed(exc):
                raise
            existing = read_s3_json_or_empty(client, bucket=bucket, key=key)
            if live_run_lock_expired(existing, now=now):
                try:
                    client.delete_object(Bucket=bucket, Key=key)
                except Exception:
                    pass
                continue
            return LiveRunLock(
                backend="s3",
                acquired=False,
                token=token,
                strategy=strategy,
                reason="live_run_lock_held",
                bucket=bucket,
                key=key,
                existing=existing,
            )
    return LiveRunLock(
        backend="s3",
        acquired=False,
        token=token,
        strategy=strategy,
        reason="live_run_lock_held",
        bucket=bucket,
        key=key,
        existing=read_s3_json_or_empty(client, bucket=bucket, key=key),
    )


def release_s3_live_run_lock(client: Any, *, bucket: str, key: str, token: str) -> None:
    existing = read_s3_json_or_empty(client, bucket=bucket, key=key)
    if existing and existing.get("token") != token:
        return
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass


def live_run_lock_s3_key(prefix: str, *, strategy: str = FAIR_VALUE_LIVE_STRATEGY) -> str:
    filename = (
        "fair-value-live-run.lock"
        if strategy == FAIR_VALUE_LIVE_STRATEGY
        else f"{strategy}-run.lock"
    )
    return "/".join(
        part.strip("/") for part in (prefix, "_locks", filename) if part
    )


def live_run_lock_expired(payload: Mapping[str, Any], *, now: datetime) -> bool:
    expires_at = parse_datetime(payload.get("expires_at"))
    return expires_at is not None and expires_at <= ensure_utc(now)


def read_json_file_or_empty(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def read_s3_json_or_empty(client: Any, *, bucket: str, key: str) -> dict[str, Any]:
    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        payload = json.loads(body)
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def s3_precondition_failed(exc: Exception) -> bool:
    code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
    return code in {"PreconditionFailed", "412"}


def live_order_request(order: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    side = str(order.get("side") or "")
    price = float(order.get("price") or 0.0)
    contracts = int(order.get("intended_contracts") or order.get("contracts") or 0)
    if side not in {"yes", "no"}:
        raise ValueError(f"unsupported fair-value order side: {side!r}")
    if contracts < 1:
        raise ValueError("fair-value live order needs at least one contract")
    yes_side_price = price if side == "yes" else 1.0 - price
    return {
        "ticker": str(order.get("ticker") or order.get("market_ticker")),
        "client_order_id": f"fv_{run_id[-15:]}_{uuid4().hex[:10]}",
        "side": "bid" if side == "yes" else "ask",
        "count": f"{float(contracts):.2f}",
        "price": f"{yes_side_price:.4f}",
        "time_in_force": "immediate_or_cancel",
        "post_only": False,
        "self_trade_prevention_type": "taker_at_cross",
        "cancel_order_on_pause": True,
    }


def order_sized_to_market_cap(
    order: Mapping[str, Any],
    *,
    remaining_ticker_exposure_dollars: float,
) -> dict[str, Any] | None:
    intended_contracts = int(order.get("intended_contracts") or order.get("contracts") or 0)
    if intended_contracts <= 0:
        return None
    per_contract_loss = order_max_loss_per_contract(order)
    if per_contract_loss <= 0:
        return None
    allowed_contracts = int(remaining_ticker_exposure_dollars // per_contract_loss)
    sized_contracts = min(intended_contracts, allowed_contracts)
    if sized_contracts <= 0:
        return None
    if sized_contracts == intended_contracts:
        return dict(order)
    price = float(order.get("price") or 0.0)
    fee_per_contract = float(order.get("fee_per_contract") or taker_fee(price, 0.07))
    cost = price * sized_contracts
    fees = fee_per_contract * sized_contracts
    return {
        **dict(order),
        "intended_contracts": sized_contracts,
        "filled_contracts": sized_contracts,
        "contracts": sized_contracts,
        "cost_dollars": round(cost, 6),
        "fees_dollars": round(fees, 6),
        "payout_dollars": 0.0,
        "pnl_dollars": 0.0,
        "max_loss_dollars": round(cost + fees, 6),
        "sized_down_reason": "market_exposure_cap",
    }


def order_max_loss_per_contract(order: Mapping[str, Any]) -> float:
    contracts = int(order.get("intended_contracts") or order.get("contracts") or 0)
    max_loss = optional_float(order.get("max_loss_dollars"))
    if contracts > 0 and max_loss is not None:
        return max_loss / contracts
    price = float(order.get("price") or 0.0)
    fee_per_contract = float(order.get("fee_per_contract") or taker_fee(price, 0.07))
    return price + fee_per_contract


def filled_max_loss_estimate(order: Mapping[str, Any], fill_count: int) -> float:
    return round(max(0, fill_count) * order_max_loss_per_contract(order), 6)


def reconcile_live_attempts(
    attempts: Sequence[Mapping[str, Any]],
    *,
    settings: Settings,
    order_client: KalshiLiveOrderClient,
    generated_at: datetime,
    max_ticker_exposure_dollars: float,
) -> dict[str, Any]:
    rows = [
        reconcile_live_attempt(
            attempt,
            settings=settings,
            order_client=order_client,
            generated_at=generated_at,
        )
        for attempt in attempts
    ]
    filled = [row for row in rows if int(row["filled_contracts"]) > 0]
    settled = [row for row in filled if row["settlement_status"] == "settled"]
    unsettled = [row for row in filled if row["settlement_status"] == "unsettled"]
    pnl = {
        "net_pnl_dollars": round(sum(float(row["pnl_dollars"]) for row in settled), 6),
        "gross_cost_dollars": round(sum(float(row["cost_dollars"]) for row in filled), 6),
        "fees_dollars": round(sum(float(row["fees_dollars"]) for row in filled), 6),
        "payout_dollars": round(sum(float(row["payout_dollars"]) for row in settled), 6),
        "unsettled_exposure_dollars": round(
            sum(float(row["max_loss_dollars"]) for row in unsettled),
            6,
        ),
        "filled_contracts": sum(int(row["filled_contracts"]) for row in filled),
        "settled_trade_count": len(settled),
        "unsettled_trade_count": len(unsettled),
    }
    return {
        "schema_version": FAIR_VALUE_LIVE_RECONCILIATION_SCHEMA,
        "generated_at": generated_at.isoformat(),
        "counts": {
            "attempts": len(rows),
            "submitted": sum(1 for row in rows if row["order_status"] == "submitted"),
            "filled": len(filled),
            "settled": len(settled),
            "unsettled": len(unsettled),
            "no_fill": sum(1 for row in rows if row["settlement_status"] == "no_fill"),
            "skipped_or_error": sum(
                1 for row in rows if row["order_status"] in {"skipped", "error", "rejected"}
            ),
        },
        "pnl": pnl,
        "settlement": {
            "status": settlement_status(settled, unsettled),
            "default_reporting": "pnl_and_settlement_included",
            "settled_rows": len(settled),
            "unsettled_rows": len(unsettled),
            "unsettled_exposure_dollars": pnl["unsettled_exposure_dollars"],
        },
        "per_market_exposure": per_market_exposure_report(
            rows,
            max_ticker_exposure_dollars=max_ticker_exposure_dollars,
        ),
        "rows": rows,
    }


def reconcile_live_attempt(
    attempt: Mapping[str, Any],
    *,
    settings: Settings,
    order_client: KalshiLiveOrderClient,
    generated_at: datetime,
) -> dict[str, Any]:
    decision = as_mapping(attempt.get("decision"))
    order_detail = order_detail_for_attempt(attempt, settings=settings, order_client=order_client)
    detail_order = as_mapping(order_detail.get("order")) if order_detail else {}
    response = as_mapping(attempt.get("response_payload"))
    filled_contracts = int(
        numeric_response_value(
            {**response, **detail_order},
            ("fill_count_fp", "fill_count", "filled_quantity"),
        )
        or attempt.get("fill_count")
        or 0
    )
    side = str(attempt.get("side") or decision.get("side") or "")
    price = float(decision.get("price") or 0.0)
    fee_per_contract = float(decision.get("fee_per_contract") or taker_fee(price, 0.07))
    cost = numeric_response_value(
        detail_order,
        ("taker_fill_cost_dollars", "maker_fill_cost_dollars"),
    )
    fees = numeric_response_value(
        detail_order,
        ("taker_fees_dollars", "maker_fees_dollars"),
    )
    cost = float(cost) if cost is not None else round(price * filled_contracts, 6)
    fees = float(fees) if fees is not None else round(fee_per_contract * filled_contracts, 6)
    market_ticker = str(attempt.get("market_ticker") or decision.get("ticker") or "")
    market_result = public_market_result(settings=settings, ticker=market_ticker)
    result = market_result.get("result")
    if filled_contracts <= 0:
        settlement = "no_fill"
        payout = 0.0
        pnl = 0.0
    elif result in {"yes", "no"}:
        settlement = "settled"
        payout = float(filled_contracts) if result == side else 0.0
        pnl = payout - cost - fees
    else:
        settlement = "unsettled"
        payout = 0.0
        pnl = 0.0
    return {
        "attempt_id": attempt.get("attempt_id"),
        "run_id": attempt.get("run_id"),
        "submitted_at": attempt.get("submitted_at"),
        "reconciled_at": generated_at.isoformat(),
        "market_ticker": market_ticker,
        "side": side,
        "order_status": attempt.get("status"),
        "order_id": attempt.get("order_id")
        or response.get("order_id")
        or detail_order.get("order_id"),
        "client_order_id": attempt.get("client_order_id")
        or response.get("client_order_id")
        or detail_order.get("client_order_id"),
        "filled_contracts": filled_contracts,
        "cost_dollars": round(cost, 6),
        "fees_dollars": round(fees, 6),
        "payout_dollars": round(payout, 6),
        "pnl_dollars": round(pnl, 6),
        "max_loss_dollars": round(cost + fees, 6),
        "settlement_status": settlement,
        "market_status": market_result.get("status"),
        "result": result,
        "order_detail_observed": bool(order_detail),
        "order_detail_error": order_detail.get("error") if order_detail else None,
    }


def order_detail_for_attempt(
    attempt: Mapping[str, Any],
    *,
    settings: Settings,
    order_client: KalshiLiveOrderClient,
) -> Mapping[str, Any]:
    order_id = attempt.get("order_id") or as_mapping(attempt.get("response_payload")).get(
        "order_id"
    )
    if not order_id:
        return {}
    try:
        return dict(order_client.get_order(order_id=str(order_id), settings=settings))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def public_market_result(*, settings: Settings, ticker: str) -> dict[str, Any]:
    if not ticker:
        return {"status": None, "result": None}
    url = f"{settings.kalshi_base_url.rstrip('/')}/markets/{parse.quote(ticker, safe='')}"
    try:
        http_request = request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "alphadb/0.1"},
            method="GET",
        )
        with request.urlopen(http_request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        market = as_mapping(payload.get("market")) if isinstance(payload, Mapping) else {}
        result = str(market.get("result") or "").lower() or None
        return {
            "status": market.get("status"),
            "result": result if result in {"yes", "no"} else None,
        }
    except Exception as exc:
        return {"status": "unknown", "result": None, "error": f"{type(exc).__name__}: {exc}"}


def daily_loss_usage_dollars(rows: Sequence[Mapping[str, Any]]) -> float:
    usage = 0.0
    for row in rows:
        if int(row.get("filled_contracts") or 0) <= 0:
            continue
        if row.get("settlement_status") == "settled":
            usage += max(0.0, -float(row.get("pnl_dollars") or 0.0))
        else:
            usage += float(row.get("max_loss_dollars") or 0.0)
    return round(usage, 6)


def daily_loss_accounting_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    generated_at: datetime,
    live_risk_timezone: str,
) -> dict[str, Any]:
    live_risk_day, window_start_utc, window_end_utc = live_risk_window(
        generated_at=generated_at,
        live_risk_timezone=live_risk_timezone,
    )
    same_day_rows = rows_for_live_risk_window(
        rows,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
    )
    filled_rows = [row for row in same_day_rows if int(row.get("filled_contracts") or 0) > 0]
    return {
        "schema_version": FAIR_VALUE_LIVE_DAILY_LOSS_ACCOUNTING_SCHEMA,
        "basis": "submitted_at_in_live_risk_day",
        "timezone": live_risk_timezone,
        "live_risk_day": live_risk_day.isoformat(),
        "window_start_utc": window_start_utc.isoformat(),
        "window_end_utc": window_end_utc.isoformat(),
        "prior_reconciliation_rows": len(rows),
        "same_live_risk_day_rows": len(same_day_rows),
        "same_live_risk_day_filled_rows": len(filled_rows),
        "same_live_risk_day_no_fill_rows": sum(
            1 for row in same_day_rows if row.get("settlement_status") == "no_fill"
        ),
        "same_live_risk_day_settled_rows": sum(
            1 for row in filled_rows if row.get("settlement_status") == "settled"
        ),
        "same_live_risk_day_unsettled_rows": sum(
            1 for row in filled_rows if row.get("settlement_status") != "settled"
        ),
        "daily_loss_used_dollars": daily_loss_usage_dollars(same_day_rows),
    }


def live_risk_window(
    *,
    generated_at: datetime,
    live_risk_timezone: str,
) -> tuple[date, datetime, datetime]:
    timezone = ZoneInfo(live_risk_timezone)
    generated_local = ensure_utc(generated_at).astimezone(timezone)
    live_risk_day = generated_local.date()
    window_start_local = datetime.combine(live_risk_day, datetime.min.time(), tzinfo=timezone)
    window_end_local = window_start_local + timedelta(days=1)
    return (
        live_risk_day,
        window_start_local.astimezone(UTC),
        window_end_local.astimezone(UTC),
    )


def rows_for_live_risk_window(
    rows: Sequence[Mapping[str, Any]],
    *,
    window_start_utc: datetime,
    window_end_utc: datetime,
) -> list[Mapping[str, Any]]:
    window_start = ensure_utc(window_start_utc)
    window_end = ensure_utc(window_end_utc)
    same_day_rows: list[Mapping[str, Any]] = []
    for row in rows:
        submitted_at = parse_datetime(row.get("submitted_at"))
        if submitted_at is None:
            continue
        if window_start <= submitted_at < window_end:
            same_day_rows.append(row)
    return same_day_rows


def per_market_exposure_dollars(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for row in rows:
        if int(row.get("filled_contracts") or 0) <= 0:
            continue
        ticker = str(row.get("market_ticker") or "")
        if not ticker:
            continue
        exposure[ticker] = exposure.get(ticker, 0.0) + float(row.get("max_loss_dollars") or 0.0)
    return {ticker: round(value, 6) for ticker, value in exposure.items()}


def per_market_exposure_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_ticker_exposure_dollars: float,
) -> dict[str, Any]:
    exposure = per_market_exposure_dollars(rows)
    return {
        "max_ticker_exposure_dollars": max_ticker_exposure_dollars,
        "markets": [
            {
                "market_ticker": ticker,
                "exposure_dollars": value,
                "remaining_dollars": round(max(0.0, max_ticker_exposure_dollars - value), 6),
                "cap_reached": value >= max_ticker_exposure_dollars,
            }
            for ticker, value in sorted(exposure.items())
        ],
    }


def summarize_attempt_reasons(attempts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reasons = sorted(
        {
            str(attempt.get("reason") or "")
            for attempt in attempts
            if attempt.get("status") == "skipped" and attempt.get("reason")
        }
    )
    return [
        {
            "reason": reason,
            "count": sum(1 for attempt in attempts if str(attempt.get("reason") or "") == reason),
        }
        for reason in reasons
    ]


def load_prior_live_attempts(
    *,
    output_root: Path,
    s3_prefix: str | None,
    current_run_id: str,
) -> list[dict[str, Any]]:
    if s3_prefix:
        return load_prior_live_attempts_from_s3(s3_prefix=s3_prefix, current_run_id=current_run_id)
    attempts: list[dict[str, Any]] = []
    for path in sorted(output_root.glob("fv_live_*/live_order_attempts.json")):
        if path.parent.name == current_run_id:
            continue
        attempts.extend(attempts_from_payload(json.loads(path.read_text(encoding="utf-8"))))
    return attempts


def load_prior_live_attempts_from_s3(
    *, s3_prefix: str, current_run_id: str
) -> list[dict[str, Any]]:
    bucket, prefix = parse_s3_prefix(s3_prefix)
    try:
        import boto3  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on AWS image environment
        raise RuntimeError("S3 prior-attempt loading requires boto3") from exc
    client = boto3.client("s3")
    key_prefix = prefix.strip("/")
    attempts: list[dict[str, Any]] = []
    continuation: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": f"{key_prefix}/"}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        payload = client.list_objects_v2(**kwargs)
        for item in payload.get("Contents", []):
            key = str(item.get("Key") or "")
            if not key.endswith("/live_order_attempts.json"):
                continue
            if f"/{current_run_id}/" in key:
                continue
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
            attempts.extend(attempts_from_payload(json.loads(body)))
        if not payload.get("IsTruncated"):
            break
        continuation = str(payload.get("NextContinuationToken") or "")
    return attempts


def attempts_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts = payload.get("attempts", [])
    if not isinstance(attempts, list):
        return []
    return [dict(attempt) for attempt in attempts if isinstance(attempt, Mapping)]


def numeric_response_value(payload: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = optional_float(payload.get(key))
        if value is not None:
            return value
    return None


def as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def as_sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def settlement_status(
    settled_rows: Sequence[Mapping[str, Any]],
    unsettled_rows: Sequence[Mapping[str, Any]],
) -> str:
    if settled_rows and unsettled_rows:
        return "partial"
    if unsettled_rows:
        return "unreconciled"
    return "reconciled"


def artifact_records(paths: Mapping[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: artifact_record(path) for name, path in paths.items()}


def artifact_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def upload_artifacts_to_s3(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    s3_prefix: str,
) -> list[dict[str, str]]:
    bucket, prefix = parse_s3_prefix(s3_prefix)
    try:
        import boto3  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on AWS image environment
        raise RuntimeError("S3 uploads require boto3") from exc
    client = boto3.client("s3")
    uploads: list[dict[str, str]] = []
    for name, record in artifacts.items():
        path = Path(str(record["path"]))
        key = "/".join(part.strip("/") for part in (prefix, path.parent.name, path.name) if part)
        client.upload_file(str(path), bucket, key)
        uploads.append({"artifact": name, "s3_uri": f"s3://{bucket}/{key}"})
    return uploads


def resolve_live_runtime_config(
    config: FairValueLiveTradingJobConfig,
    *,
    settings: Settings,
) -> tuple[FairValueLiveTradingJobConfig, dict[str, Any]]:
    source = config.runtime_config_source
    if source == "auto" and settings.environment.lower() not in AWS_LIKE_ENVIRONMENTS:
        return config, {
            "source": "cli_local_fallback",
            "strategy": config.strategy,
            "config_id": None,
            "version": None,
            "snapshot": {
                "strategy": config.strategy,
                "decision_policy": config.decision_policy,
                "max_order_dollars": config.max_order_dollars,
                "max_market_exposure_dollars": config.max_ticker_exposure_dollars,
                "max_daily_loss_dollars": config.max_daily_loss_dollars,
                "min_edge": config.min_edge,
                "min_contract_price": config.min_contract_price,
                "max_markets": config.max_markets,
                "market_context_source": config.market_context_source,
                "brti_future_tolerance_seconds": config.brti_future_tolerance_seconds,
            },
        }
    if source == "cli":
        return config, {
            "source": "cli",
            "strategy": config.strategy,
            "config_id": None,
            "version": None,
            "snapshot": {
                "strategy": config.strategy,
                "decision_policy": config.decision_policy,
                "max_order_dollars": config.max_order_dollars,
                "max_market_exposure_dollars": config.max_ticker_exposure_dollars,
                "max_daily_loss_dollars": config.max_daily_loss_dollars,
                "min_edge": config.min_edge,
                "min_contract_price": config.min_contract_price,
                "max_markets": config.max_markets,
                "market_context_source": config.market_context_source,
                "brti_future_tolerance_seconds": config.brti_future_tolerance_seconds,
            },
        }
    try:
        revision = LiveRuntimeConfigRepository(settings.database_url).seed_defaults(
            strategy=config.strategy
        )
    except Exception as exc:
        if source == "postgres" or settings.environment.lower() in AWS_LIKE_ENVIRONMENTS:
            raise RuntimeError("dashboard-owned live runtime config is unavailable") from exc
        return config, {
            "source": "cli_db_unavailable_fallback",
            "strategy": config.strategy,
            "config_id": None,
            "version": None,
            "error": f"{type(exc).__name__}: {exc}",
            "snapshot": {
                "strategy": config.strategy,
                "decision_policy": config.decision_policy,
                "max_order_dollars": config.max_order_dollars,
                "max_market_exposure_dollars": config.max_ticker_exposure_dollars,
                "max_daily_loss_dollars": config.max_daily_loss_dollars,
                "min_edge": config.min_edge,
                "min_contract_price": config.min_contract_price,
                "max_markets": config.max_markets,
                "market_context_source": config.market_context_source,
                "brti_future_tolerance_seconds": config.brti_future_tolerance_seconds,
            },
        }
    dashboard_config = revision.config
    effective = replace(
        config,
        max_markets=dashboard_config.max_markets,
        min_edge=dashboard_config.min_edge,
        min_contract_price=dashboard_config.min_contract_price,
        market_context_source=dashboard_config.market_context_source,
        max_order_dollars=dashboard_config.max_order_dollars,
        max_ticker_exposure_dollars=dashboard_config.max_market_exposure_dollars,
        max_daily_loss_dollars=dashboard_config.max_daily_loss_dollars,
    )
    return effective, {
        "source": "dashboard_postgres",
        **revision.manifest_snapshot(),
    }


def materialize_live_run_status(
    *,
    settings: Settings,
    manifest: Mapping[str, Any],
    live_attempts_payload: Mapping[str, Any],
    live_reconciliation: Mapping[str, Any],
    require_postgres: bool,
) -> None:
    try:
        status = build_fair_value_live_status(
            manifest=manifest,
            attempts_payload=live_attempts_payload,
            reconciliation=live_reconciliation,
        )
        LiveRunStatusRepository(settings.database_url).persist(status)
    except Exception:
        if require_postgres:
            raise


def parse_s3_prefix(value: str) -> tuple[str, str]:
    if not value.startswith("s3://"):
        raise ValueError("--s3-prefix must start with s3://")
    rest = value.removeprefix("s3://")
    bucket, _, prefix = rest.partition("/")
    if not bucket:
        raise ValueError("--s3-prefix must include a bucket")
    return bucket, prefix


def parse_live_job_min_edge_values(value: str) -> tuple[float, ...]:
    parsed = tuple(parse_min_edge_values(value))
    if not parsed:
        raise ValueError("at least one min-edge value is required")
    return parsed


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ensure_utc(parsed)
