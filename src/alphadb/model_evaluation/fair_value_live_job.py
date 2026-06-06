"""Capped live-money fair-value canary job."""

from __future__ import annotations

import json
import os
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
    exchange_response_accepted,
    materialize_private_key_from_env,
)
from alphadb.live_runtime import (
    LiveRunStatusRepository,
    LiveRuntimeConfigRepository,
    build_fair_value_live_status,
)
from alphadb.model_evaluation.fair_value_live import (
    FairValueDecisionRowCollector,
    FairValueDecisionRowCollectorConfig,
    make_coinbase_client,
    make_kalshi_client,
)
from alphadb.model_evaluation.fair_value_replay import (
    FairValueReplayConfig,
    build_fair_value_replay_report,
    build_fair_value_walk_forward_report,
    parse_min_edge_values,
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
AWS_LIKE_ENVIRONMENTS = {"aws", "prod", "production"}


@dataclass(frozen=True)
class FairValueLiveTradingJobConfig:
    output_root: Path
    source: str = "fixture"
    coinbase_source: str = "fixture"
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_root": str(self.output_root),
            "source": self.source,
            "coinbase_source": self.coinbase_source,
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
        self._settings = settings
        self.order_client = order_client or HttpKalshiLiveOrderClient()

    def run(self, *, now: datetime | None = None) -> dict[str, Any]:
        materialize_private_key_from_env()
        settings = self._settings or settings_from_env()
        original_config = self.config
        effective_config, runtime_config = resolve_live_runtime_config(
            original_config,
            settings=settings,
        )
        self.config = effective_config
        generated_at = ensure_utc(now or datetime.now(UTC))
        run_id = f"fv_live_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
        run_dir = self.config.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        collector = FairValueDecisionRowCollector(
            kalshi_client=make_kalshi_client(self.config.source, settings),
            coinbase_client=make_coinbase_client(self.config.coinbase_source),
            settings=settings,
            config=FairValueDecisionRowCollectorConfig(
                max_markets=self.config.max_markets,
                run_id=run_id,
                source_mode=self.config.source,
                coinbase_source_mode=self.config.coinbase_source,
            ),
        )
        collected = collector.collect(now=generated_at).as_dict()
        rows = [row for row in collected["rows"] if row.get("row_type") == "decision"]
        replay = build_fair_value_replay_report(
            rows,
            config=FairValueReplayConfig(
                min_edge=self.config.min_edge,
                min_contract_price=self.config.min_contract_price,
                max_order_dollars=self.config.max_order_dollars,
                max_loss_dollars=self.config.max_daily_loss_dollars,
            ),
        )
        walk_forward = build_fair_value_walk_forward_report(
            rows,
            selection_market_count=self.config.selection_market_count,
            holdout_market_count=self.config.holdout_market_count,
            step_market_count=self.config.step_market_count,
            min_edge_values=self.config.min_edge_values,
            min_contract_price=self.config.min_contract_price,
            max_order_dollars=self.config.max_order_dollars,
            max_loss_dollars=self.config.max_daily_loss_dollars,
        )

        live_run_lock = acquire_live_run_lock(
            output_root=self.config.output_root,
            s3_prefix=self.config.s3_prefix,
            run_id=run_id,
            generated_at=generated_at,
            enabled=self.config.submit_live_orders,
        )
        try:
            prior_attempts = load_prior_live_attempts(
                output_root=self.config.output_root,
                s3_prefix=self.config.s3_prefix,
                current_run_id=run_id,
            )
            prior_reconciliation = reconcile_live_attempts(
                prior_attempts,
                settings=settings,
                order_client=self.order_client,
                generated_at=generated_at,
                max_ticker_exposure_dollars=self.config.max_ticker_exposure_dollars,
            )
            admission_daily_loss_accounting = daily_loss_accounting_report(
                prior_reconciliation["rows"],
                generated_at=generated_at,
                live_risk_timezone=self.config.live_risk_timezone,
            )
            daily_loss_used = float(admission_daily_loss_accounting["daily_loss_used_dollars"])
            market_exposure_by_ticker = per_market_exposure_dollars(prior_reconciliation["rows"])
            live_attempts = self._submit_live_attempts(
                replay_decisions=replay["decisions"],
                settings=settings,
                run_id=run_id,
                generated_at=generated_at,
                starting_daily_loss_used=daily_loss_used,
                daily_loss_accounting=admission_daily_loss_accounting,
                market_exposure_by_ticker=market_exposure_by_ticker,
                live_run_lock=live_run_lock,
            )
            live_attempts_payload = {
                "schema_version": FAIR_VALUE_LIVE_ATTEMPTS_SCHEMA,
                "run_id": run_id,
                "generated_at": generated_at.isoformat(),
                "admission_daily_loss_accounting": admission_daily_loss_accounting,
                "skip_reasons": summarize_attempt_reasons(live_attempts),
                "attempts": live_attempts,
            }
            live_reconciliation = reconcile_live_attempts(
                [*prior_attempts, *live_attempts],
                settings=settings,
                order_client=self.order_client,
                generated_at=generated_at,
                max_ticker_exposure_dollars=self.config.max_ticker_exposure_dollars,
            )
            daily_loss_accounting = daily_loss_accounting_report(
                live_reconciliation["rows"],
                generated_at=generated_at,
                live_risk_timezone=self.config.live_risk_timezone,
            )
            live_attempts_payload["daily_loss_accounting"] = daily_loss_accounting

            artifacts = {
                "decision_rows": run_dir / "decision_rows.json",
                "replay_report": run_dir / "replay_report.json",
                "walk_forward_report": run_dir / "walk_forward_report.json",
                "live_order_attempts": run_dir / "live_order_attempts.json",
                "live_reconciliation_report": run_dir / "live_reconciliation_report.json",
            }
            write_json(artifacts["decision_rows"], collected)
            write_json(artifacts["replay_report"], replay)
            write_json(artifacts["walk_forward_report"], walk_forward)
            write_json(artifacts["live_order_attempts"], live_attempts_payload)
            write_json(artifacts["live_reconciliation_report"], live_reconciliation)

            guard = evaluate_runtime_guard(settings)
            orders_placed = sum(1 for attempt in live_attempts if attempt["status"] == "submitted")
            filled_contracts = sum(int(attempt.get("fill_count") or 0) for attempt in live_attempts)
            manifest = {
                "schema_version": FAIR_VALUE_LIVE_JOB_SCHEMA,
                "run_id": run_id,
                "generated_at": generated_at.isoformat(),
                "config": self.config.as_dict(),
                "runtime_config": runtime_config,
                "runtime_controls": {
                    "report_only": False,
                    "submit_live_orders_requested": self.config.submit_live_orders,
                    "live_orders_enabled": guard.can_submit_live_orders,
                    "orders_placed": orders_placed,
                    "filled_contracts": filled_contracts,
                    "max_order_dollars": self.config.max_order_dollars,
                    "max_market_exposure_dollars": self.config.max_ticker_exposure_dollars,
                    "max_ticker_exposure_dollars": self.config.max_ticker_exposure_dollars,
                    "max_daily_loss_dollars": self.config.max_daily_loss_dollars,
                    "min_contract_price": self.config.min_contract_price,
                    "admission_daily_loss_accounting": admission_daily_loss_accounting,
                    "daily_loss_accounting": daily_loss_accounting,
                    "runtime_guard": guard.as_dict(),
                    "live_run_lock": live_run_lock.as_dict(),
                    "live_status_materialized": should_materialize_live_run_status(live_run_lock),
                },
                "counts": {
                    "collected_rows": collected["counts"]["rows"],
                    "decision_rows": collected["counts"]["decisions"],
                    "skip_rows": collected["counts"]["skips"],
                    "replay_trades": replay["counts"]["trades"],
                    "walk_forward_windows": walk_forward["complete_window_count"],
                    "live_attempts": len(live_attempts),
                    "live_skipped": sum(
                        1 for attempt in live_attempts if attempt.get("status") == "skipped"
                    ),
                    "prior_live_attempts_reconciled": len(prior_attempts),
                    "prior_reconciliation_rows_for_daily_loss": admission_daily_loss_accounting[
                        "same_live_risk_day_rows"
                    ],
                    "live_reconciliation_rows_for_daily_loss": daily_loss_accounting[
                        "same_live_risk_day_rows"
                    ],
                },
                "report_summary": {
                    "simulated_replay_net_pnl_dollars": replay["pnl"]["net_pnl_dollars"],
                    "simulated_replay_settlement_status": replay["settlement"]["status"],
                    "daily_loss_live_risk_day": daily_loss_accounting["live_risk_day"],
                    "daily_loss_used_dollars": daily_loss_accounting["daily_loss_used_dollars"],
                    "live_reconciliation_scope": "full_history_loaded_attempts",
                    "live_full_history_net_pnl_dollars": live_reconciliation["pnl"][
                        "net_pnl_dollars"
                    ],
                    "live_full_history_unsettled_exposure_dollars": live_reconciliation["pnl"][
                        "unsettled_exposure_dollars"
                    ],
                    "live_daily_net_pnl_dollars": live_reconciliation["pnl"]["net_pnl_dollars"],
                    "live_daily_unsettled_exposure_dollars": live_reconciliation["pnl"][
                        "unsettled_exposure_dollars"
                    ],
                    "live_settlement_status": live_reconciliation["settlement"]["status"],
                    "live_attempt_skip_reasons": summarize_attempt_reasons(live_attempts),
                },
                "artifacts": artifact_records(artifacts),
            }
            if should_materialize_live_run_status(live_run_lock):
                materialize_live_run_status(
                    settings=settings,
                    manifest=manifest,
                    live_attempts_payload=live_attempts_payload,
                    live_reconciliation=live_reconciliation,
                    require_postgres=runtime_config.get("source") == "dashboard_postgres",
                )
            write_json(run_dir / "manifest.json", manifest)
            manifest["artifacts"]["manifest"] = artifact_record(run_dir / "manifest.json")
            if self.config.s3_prefix:
                manifest["s3_uploads"] = upload_artifacts_to_s3(
                    manifest["artifacts"],
                    s3_prefix=self.config.s3_prefix,
                )
                write_json(run_dir / "manifest.json", manifest)
                manifest["artifacts"]["manifest"] = artifact_record(run_dir / "manifest.json")
            return manifest
        finally:
            self.config = original_config
            live_run_lock.release()

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


@dataclass
class LiveRunLock:
    backend: str
    acquired: bool
    token: str
    reason: str | None = None
    path: Path | None = None
    bucket: str | None = None
    key: str | None = None
    existing: Mapping[str, Any] | None = None
    client: Any = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": FAIR_VALUE_LIVE_LOCK_SCHEMA,
            "backend": self.backend,
            "acquired": self.acquired,
            "token": self.token,
            "reason": self.reason,
        }
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


def should_materialize_live_run_status(live_run_lock: LiveRunLock) -> bool:
    return live_run_lock.acquired or live_run_lock.reason != "live_run_lock_held"


def acquire_live_run_lock(
    *,
    output_root: Path,
    s3_prefix: str | None,
    run_id: str,
    generated_at: datetime,
    enabled: bool,
    ttl_seconds: int = FAIR_VALUE_LIVE_LOCK_TTL_SECONDS,
) -> LiveRunLock:
    if not enabled:
        return LiveRunLock(
            backend="none",
            acquired=True,
            token="",
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
            token=token,
            payload=payload,
            now=generated_at,
        )
    return acquire_local_live_run_lock(
        output_root=output_root,
        token=token,
        payload=payload,
        now=generated_at,
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
    token: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> LiveRunLock:
    path = output_root / ".fair_value_live_run.lock"
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
                reason="live_run_lock_held",
                path=path,
                existing=existing,
            )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True)
        return LiveRunLock(backend="local", acquired=True, token=token, path=path)
    return LiveRunLock(
        backend="local",
        acquired=False,
        token=token,
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
    token: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> LiveRunLock:
    bucket, prefix = parse_s3_prefix(s3_prefix)
    key = live_run_lock_s3_key(prefix)
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
                reason="live_run_lock_held",
                bucket=bucket,
                key=key,
                existing=existing,
            )
    return LiveRunLock(
        backend="s3",
        acquired=False,
        token=token,
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


def live_run_lock_s3_key(prefix: str) -> str:
    return "/".join(
        part.strip("/") for part in (prefix, "_locks", "fair-value-live-run.lock") if part
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
            "config_id": None,
            "version": None,
            "snapshot": {
                "max_order_dollars": config.max_order_dollars,
                "max_market_exposure_dollars": config.max_ticker_exposure_dollars,
                "max_daily_loss_dollars": config.max_daily_loss_dollars,
                "min_edge": config.min_edge,
                "min_contract_price": config.min_contract_price,
                "max_markets": config.max_markets,
            },
        }
    if source == "cli":
        return config, {
            "source": "cli",
            "config_id": None,
            "version": None,
            "snapshot": {
                "max_order_dollars": config.max_order_dollars,
                "max_market_exposure_dollars": config.max_ticker_exposure_dollars,
                "max_daily_loss_dollars": config.max_daily_loss_dollars,
                "min_edge": config.min_edge,
                "min_contract_price": config.min_contract_price,
                "max_markets": config.max_markets,
            },
        }
    try:
        revision = LiveRuntimeConfigRepository(settings.database_url).seed_defaults()
    except Exception as exc:
        if source == "postgres" or settings.environment.lower() in AWS_LIKE_ENVIRONMENTS:
            raise RuntimeError("dashboard-owned live runtime config is unavailable") from exc
        return config, {
            "source": "cli_db_unavailable_fallback",
            "config_id": None,
            "version": None,
            "error": f"{type(exc).__name__}: {exc}",
            "snapshot": {
                "max_order_dollars": config.max_order_dollars,
                "max_market_exposure_dollars": config.max_ticker_exposure_dollars,
                "max_daily_loss_dollars": config.max_daily_loss_dollars,
                "min_edge": config.min_edge,
                "min_contract_price": config.min_contract_price,
                "max_markets": config.max_markets,
            },
        }
    dashboard_config = revision.config
    effective = replace(
        config,
        max_markets=dashboard_config.max_markets,
        min_edge=dashboard_config.min_edge,
        min_contract_price=dashboard_config.min_contract_price,
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
