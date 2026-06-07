"""Bounded live-risk refresh evidence resolution.

This module is intentionally deterministic. It does not query the exchange or
mutate Operational State; callers provide already-collected evidence and receive
the pending-reservation action that is safe to apply.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from alphadb.config import Settings
from alphadb.live_orders import KalshiLiveOrderClient, LiveOrderRepository, safe_http_status
from alphadb.live_risk import (
    UNRESOLVED_PENDING_RESERVATION_REASON,
    LiveRiskAdmissionRepository,
    LiveRiskAdmissionState,
    state_denial_reason,
)


EvidenceKind = Literal[
    "order",
    "negative_lookup",
    "unreachable",
    "timeout",
    "ambiguous_http",
    "unsupported_lookup",
    "artifact_only",
    "missing_identifier",
]
ResolutionAction = Literal["release", "convert", "preserve", "block"]


@dataclass(frozen=True)
class PendingReservation:
    reservation_id: str
    market_ticker: str
    max_loss_dollars: float
    intended_quantity: float
    client_order_id: str | None = None
    order_id: str | None = None
    time_in_force: str | None = "immediate_or_cancel"


@dataclass(frozen=True)
class ExchangeOrderEvidence:
    kind: EvidenceKind
    status: str | None = None
    fill_count: float | None = None
    remaining_count: float | None = None
    authoritative_no_order: bool = False
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PendingReservationResolution:
    reservation_id: str
    action: ResolutionAction
    reason: str
    release_max_loss_dollars: float = 0.0
    convert_max_loss_dollars: float = 0.0
    preserve_max_loss_dollars: float = 0.0
    blocked_reason: str | None = None
    abnormal_reason: str | None = None
    evidence: Mapping[str, Any] | None = None

    @property
    def blocks_admission(self) -> bool:
        return self.action == "block"

    def as_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "action": self.action,
            "reason": self.reason,
            "release_max_loss_dollars": round(self.release_max_loss_dollars, 6),
            "convert_max_loss_dollars": round(self.convert_max_loss_dollars, 6),
            "preserve_max_loss_dollars": round(self.preserve_max_loss_dollars, 6),
            "blocked_reason": self.blocked_reason,
            "abnormal_reason": self.abnormal_reason,
            "evidence": dict(self.evidence or {}),
        }


@dataclass(frozen=True)
class BoundedRefreshLimits:
    max_lookup_count: int = 3
    max_elapsed_seconds: float = 2.0
    per_lookup_timeout_seconds: float = 1.0


@dataclass(frozen=True)
class BoundedRefreshResult:
    status: str
    reason: str
    ran: bool
    lookup_count: int = 0
    lookup_limit: int = 0
    timeout_seconds: float = 0.0
    unresolved_reservation_ids: tuple[str, ...] = ()
    resolutions: tuple[PendingReservationResolution, ...] = ()
    state: LiveRiskAdmissionState | None = None
    state_version_after: int | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "ran": self.ran,
            "lookup_count": self.lookup_count,
            "lookup_limit": self.lookup_limit,
            "timeout_seconds": self.timeout_seconds,
            "unresolved_reservation_ids": list(self.unresolved_reservation_ids),
            "unresolved_reservation_count": len(self.unresolved_reservation_ids),
            "resolutions": [resolution.as_dict() for resolution in self.resolutions],
            "state_status": self.state.status if self.state else None,
            "state_version_after": self.state_version_after,
            "message": self.message,
        }


def should_refresh_state(
    state: LiveRiskAdmissionState | None,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> bool:
    if state is None:
        return False
    if state.pending_reservations:
        return True
    if state.status == "blocked":
        return True
    return (
        state_denial_reason(state, now=now, stale_after_seconds=stale_after_seconds)
        == "risk_state_stale"
    )


def bounded_refresh_before_admission(
    *,
    risk_repository: LiveRiskAdmissionRepository,
    order_repository: LiveOrderRepository,
    order_client: KalshiLiveOrderClient,
    settings: Settings,
    state: LiveRiskAdmissionState | None,
    strategy: str,
    live_risk_day: date,
    now: datetime,
    run_id: str,
    stale_after_seconds: int,
    limits: BoundedRefreshLimits | None = None,
) -> BoundedRefreshResult:
    limits = limits or BoundedRefreshLimits()
    if not should_refresh_state(state, now=now, stale_after_seconds=stale_after_seconds):
        return BoundedRefreshResult(
            status="skipped",
            reason="state_not_refreshable",
            ran=False,
            lookup_limit=limits.max_lookup_count,
            timeout_seconds=limits.max_elapsed_seconds,
            state=state,
            state_version_after=state.version if state else None,
        )
    claim = risk_repository.claim_refresh(
        strategy=strategy,
        live_risk_day=live_risk_day,
        now=now,
        run_id=run_id,
    )
    if not claim.approved or claim.state is None:
        return BoundedRefreshResult(
            status="failed",
            reason=claim.reason,
            ran=True,
            lookup_limit=limits.max_lookup_count,
            timeout_seconds=limits.max_elapsed_seconds,
            state=claim.state or state,
            state_version_after=claim.state_version_after,
            message=claim.message,
        )
    claimed_state = claim.state
    reservation_ids = tuple(sorted(claimed_state.pending_reservations))
    attempts = order_repository.attempts_for_reservations(
        strategy=strategy,
        live_risk_day=live_risk_day,
        reservation_ids=reservation_ids,
        limit=max(limits.max_lookup_count, len(reservation_ids), 1),
    )
    attempt_by_reservation = latest_attempt_by_reservation(attempts)
    started = time.monotonic()
    lookup_count = 0
    resolutions: list[PendingReservationResolution] = []
    for reservation_id in reservation_ids:
        reservation_payload = claimed_state.pending_reservations[reservation_id]
        attempt = attempt_by_reservation.get(reservation_id)
        reservation = pending_reservation_from_payload(
            reservation_id,
            reservation_payload_with_attempt(reservation_payload, attempt),
        )
        if lookup_count >= limits.max_lookup_count:
            resolutions.append(
                resolve_pending_reservation(
                    reservation,
                    ExchangeOrderEvidence(
                        kind="timeout",
                        metadata={"reason": "lookup_limit_exceeded"},
                    ),
                )
            )
            continue
        if time.monotonic() - started >= limits.max_elapsed_seconds:
            resolutions.append(
                resolve_pending_reservation(
                    reservation,
                    ExchangeOrderEvidence(
                        kind="timeout",
                        metadata={"reason": "refresh_time_limit_exceeded"},
                    ),
                )
            )
            continue
        evidence = exchange_evidence_for_reservation(
            reservation,
            attempt=attempt,
            order_client=order_client,
            settings=settings,
            timeout_seconds=limits.per_lookup_timeout_seconds,
        )
        if evidence.kind not in {"artifact_only", "missing_identifier", "unsupported_lookup"}:
            lookup_count += 1
        resolutions.append(resolve_pending_reservation(reservation, evidence))
    complete = risk_repository.complete_refresh(
        strategy=strategy,
        live_risk_day=live_risk_day,
        expected_version=claimed_state.version,
        resolutions=[resolution.as_dict() for resolution in resolutions],
        now=now,
        metadata={
            "last_refresh": {
                "run_id": run_id,
                "lookup_count": lookup_count,
                "lookup_limit": limits.max_lookup_count,
                "timeout_seconds": limits.max_elapsed_seconds,
                "resolutions": [resolution.as_dict() for resolution in resolutions],
            },
        },
    )
    if not complete.approved or complete.state is None:
        return BoundedRefreshResult(
            status="failed",
            reason=complete.reason,
            ran=True,
            lookup_count=lookup_count,
            lookup_limit=limits.max_lookup_count,
            timeout_seconds=limits.max_elapsed_seconds,
            unresolved_reservation_ids=reservation_ids,
            resolutions=tuple(resolutions),
            state=complete.state or claimed_state,
            state_version_after=complete.state_version_after,
            message=complete.message,
        )
    unresolved = tuple(
        resolution.reservation_id
        for resolution in resolutions
        if resolution.action in {"block", "preserve"}
    )
    return BoundedRefreshResult(
        status="blocked" if unresolved else "active",
        reason="unresolved_pending_reservation" if unresolved else "refresh_resolved",
        ran=True,
        lookup_count=lookup_count,
        lookup_limit=limits.max_lookup_count,
        timeout_seconds=limits.max_elapsed_seconds,
        unresolved_reservation_ids=unresolved,
        resolutions=tuple(resolutions),
        state=complete.state,
        state_version_after=complete.state.version,
    )


def resolve_pending_reservation(
    reservation: PendingReservation,
    evidence: ExchangeOrderEvidence,
) -> PendingReservationResolution:
    evidence_summary = evidence_as_dict(evidence)
    if not reservation.client_order_id and not reservation.order_id:
        return _blocked(
            reservation,
            "missing_exchange_identifier",
            evidence=evidence_summary,
        )
    if evidence.kind in {
        "unreachable",
        "timeout",
        "ambiguous_http",
        "unsupported_lookup",
        "artifact_only",
        "missing_identifier",
    }:
        return _blocked(reservation, evidence.kind, evidence=evidence_summary)
    if evidence.kind == "negative_lookup":
        if evidence.authoritative_no_order:
            return PendingReservationResolution(
                reservation_id=reservation.reservation_id,
                action="release",
                reason="authoritative_no_order",
                release_max_loss_dollars=round(reservation.max_loss_dollars, 6),
                evidence=evidence_summary,
            )
        return _blocked(reservation, "ambiguous_negative_lookup", evidence=evidence_summary)
    if evidence.kind != "order":
        return _blocked(reservation, f"unsupported_evidence:{evidence.kind}", evidence=evidence_summary)

    status = normalize_order_status(evidence.status)
    fill_count = max(0.0, float(evidence.fill_count or 0.0))
    remaining_count = (
        max(0.0, float(evidence.remaining_count))
        if evidence.remaining_count is not None
        else None
    )
    filled_max_loss = filled_max_loss_for(reservation, fill_count)
    if status in {"canceled", "cancelled", "rejected", "expired", "failed"}:
        return _convert_or_release(
            reservation,
            filled_max_loss=filled_max_loss,
            reason=f"terminal_{status}",
            evidence=evidence_summary,
        )
    if status in {"filled", "executed"}:
        return _convert_or_release(
            reservation,
            filled_max_loss=filled_max_loss,
            reason=status,
            evidence=evidence_summary,
        )
    if status in {"open", "resting", "pending"}:
        abnormal = (
            "unexpected_open_ioc_order"
            if normalize_time_in_force(reservation.time_in_force) == "immediate_or_cancel"
            else None
        )
        return PendingReservationResolution(
            reservation_id=reservation.reservation_id,
            action="preserve",
            reason=status,
            preserve_max_loss_dollars=round(reservation.max_loss_dollars - filled_max_loss, 6),
            convert_max_loss_dollars=round(filled_max_loss, 6),
            abnormal_reason=abnormal,
            evidence=evidence_summary,
        )
    if status in {"accepted", "submitted"}:
        if fill_count > 0:
            if remaining_count is None or remaining_count > 0:
                return PendingReservationResolution(
                    reservation_id=reservation.reservation_id,
                    action="preserve",
                    reason="partial_fill_unresolved_remaining",
                    preserve_max_loss_dollars=round(
                        reservation.max_loss_dollars - filled_max_loss,
                        6,
                    ),
                    convert_max_loss_dollars=round(filled_max_loss, 6),
                    evidence=evidence_summary,
                )
            return _convert_or_release(
                reservation,
                filled_max_loss=filled_max_loss,
                reason="partial_fill_terminal_no_remainder",
                evidence=evidence_summary,
            )
        if remaining_count == 0:
            return PendingReservationResolution(
                reservation_id=reservation.reservation_id,
                action="release",
                reason="confirmed_no_fill",
                release_max_loss_dollars=round(reservation.max_loss_dollars, 6),
                evidence=evidence_summary,
            )
        return _blocked(reservation, "accepted_without_fill_or_remaining", evidence=evidence_summary)
    return _blocked(reservation, f"unknown_order_status:{status or 'missing'}", evidence=evidence_summary)


def latest_attempt_by_reservation(
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for attempt in attempts:
        reservation_id = _optional_text(attempt.get("reservation_id"))
        if reservation_id and reservation_id not in output:
            output[reservation_id] = attempt
    return output


def reservation_payload_with_attempt(
    reservation_payload: Mapping[str, Any],
    attempt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(reservation_payload)
    if not attempt:
        return payload
    response = _mapping(attempt.get("response_payload"))
    for source_key, target_key in (
        ("client_order_id", "client_order_id"),
        ("exchange_order_id", "order_id"),
        ("intended_side", "intended_side"),
        ("intended_quantity", "intended_quantity"),
        ("intended_max_loss_dollars", "max_loss_dollars"),
    ):
        value = attempt.get(source_key)
        if value not in (None, ""):
            payload[target_key] = value
    if "order_id" not in payload and response.get("order_id"):
        payload["order_id"] = response.get("order_id")
    request_payload = _mapping(attempt.get("request_payload"))
    if "time_in_force" not in payload and request_payload.get("time_in_force"):
        payload["time_in_force"] = request_payload.get("time_in_force")
    return payload


def exchange_evidence_for_reservation(
    reservation: PendingReservation,
    *,
    attempt: Mapping[str, Any] | None,
    order_client: KalshiLiveOrderClient,
    settings: Settings,
    timeout_seconds: float,
) -> ExchangeOrderEvidence:
    if not attempt:
        return ExchangeOrderEvidence(kind="artifact_only", metadata={"reason": "missing_attempt_record"})
    if not reservation.order_id and not reservation.client_order_id:
        return ExchangeOrderEvidence(kind="missing_identifier")
    try:
        if reservation.order_id:
            payload = get_order_detail(
                order_client,
                order_id=reservation.order_id,
                settings=settings,
                timeout_seconds=timeout_seconds,
            )
        elif reservation.client_order_id and hasattr(order_client, "get_order_by_client_order_id"):
            payload = order_client.get_order_by_client_order_id(  # type: ignore[attr-defined]
                client_order_id=reservation.client_order_id,
                settings=settings,
                timeout_seconds=timeout_seconds,
            )
        else:
            return ExchangeOrderEvidence(
                kind="unsupported_lookup",
                metadata={"lookup": "client_order_id"},
            )
    except TimeoutError as exc:
        return ExchangeOrderEvidence(kind="timeout", metadata={"message": str(exc)})
    except Exception as exc:
        http_status = safe_http_status(exc)
        return ExchangeOrderEvidence(
            kind="ambiguous_http" if http_status else "unreachable",
            metadata={
                "error_class": type(exc).__name__,
                "message": str(exc),
                **({"http_status": http_status} if http_status is not None else {}),
            },
        )
    return evidence_from_order_detail(payload)


def get_order_detail(
    order_client: KalshiLiveOrderClient,
    *,
    order_id: str,
    settings: Settings,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    try:
        return dict(
            order_client.get_order(
                order_id=order_id,
                settings=settings,
                timeout_seconds=timeout_seconds,
            )
        )
    except TypeError:
        return dict(order_client.get_order(order_id=order_id, settings=settings))


def evidence_from_order_detail(payload: Mapping[str, Any]) -> ExchangeOrderEvidence:
    if payload.get("authoritative_no_order"):
        return ExchangeOrderEvidence(
            kind="negative_lookup",
            authoritative_no_order=True,
            metadata=dict(payload),
        )
    if payload.get("not_found"):
        return ExchangeOrderEvidence(
            kind="negative_lookup",
            authoritative_no_order=False,
            metadata=dict(payload),
        )
    order = _mapping(payload.get("order")) or payload
    if not order:
        return ExchangeOrderEvidence(kind="ambiguous_http", metadata={"reason": "empty_order_detail"})
    return ExchangeOrderEvidence(
        kind="order",
        status=_optional_text(order.get("status") or payload.get("status")),
        fill_count=_numeric(order, payload, keys=("fill_count", "fill_count_fp", "filled_quantity")),
        remaining_count=_numeric(
            order,
            payload,
            keys=("remaining_count", "remaining_count_fp", "remaining_quantity"),
        ),
        metadata=dict(payload),
    )


def pending_reservation_from_payload(
    reservation_id: str,
    payload: Mapping[str, Any],
) -> PendingReservation:
    return PendingReservation(
        reservation_id=reservation_id,
        market_ticker=str(payload.get("market_ticker") or ""),
        max_loss_dollars=float(payload.get("max_loss_dollars") or 0.0),
        intended_quantity=float(
            payload.get("intended_quantity")
            or payload.get("quantity")
            or payload.get("contracts")
            or 1.0
        ),
        client_order_id=_optional_text(payload.get("client_order_id")),
        order_id=_optional_text(payload.get("order_id")),
        time_in_force=_optional_text(payload.get("time_in_force")) or "immediate_or_cancel",
    )


def evidence_as_dict(evidence: ExchangeOrderEvidence) -> dict[str, Any]:
    return {
        "kind": evidence.kind,
        "status": evidence.status,
        "fill_count": evidence.fill_count,
        "remaining_count": evidence.remaining_count,
        "authoritative_no_order": evidence.authoritative_no_order,
        "metadata": dict(evidence.metadata or {}),
    }


def normalize_order_status(status: str | None) -> str:
    return str(status or "").strip().lower().replace("-", "_")


def normalize_time_in_force(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def filled_max_loss_for(reservation: PendingReservation, fill_count: float) -> float:
    quantity = max(float(reservation.intended_quantity or 0.0), fill_count, 0.0)
    if quantity <= 0 or fill_count <= 0:
        return 0.0
    ratio = min(fill_count / quantity, 1.0)
    return round(reservation.max_loss_dollars * ratio, 6)


def _convert_or_release(
    reservation: PendingReservation,
    *,
    filled_max_loss: float,
    reason: str,
    evidence: Mapping[str, Any],
) -> PendingReservationResolution:
    release = max(0.0, reservation.max_loss_dollars - filled_max_loss)
    if filled_max_loss > 0:
        return PendingReservationResolution(
            reservation_id=reservation.reservation_id,
            action="convert",
            reason=reason,
            release_max_loss_dollars=round(release, 6),
            convert_max_loss_dollars=round(filled_max_loss, 6),
            evidence=evidence,
        )
    return PendingReservationResolution(
        reservation_id=reservation.reservation_id,
        action="release",
        reason=reason,
        release_max_loss_dollars=round(reservation.max_loss_dollars, 6),
        evidence=evidence,
    )


def _blocked(
    reservation: PendingReservation,
    reason: str,
    *,
    evidence: Mapping[str, Any],
) -> PendingReservationResolution:
    return PendingReservationResolution(
        reservation_id=reservation.reservation_id,
        action="block",
        reason=reason,
        preserve_max_loss_dollars=round(reservation.max_loss_dollars, 6),
        blocked_reason=UNRESOLVED_PENDING_RESERVATION_REASON,
        evidence=evidence,
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _numeric(
    *sources: Mapping[str, Any],
    keys: Sequence[str],
) -> float | None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None
