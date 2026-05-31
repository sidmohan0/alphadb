"""Gated-live Kalshi order adapter."""

from __future__ import annotations

import argparse
import base64
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib import request
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from alphadb.config import Settings, settings_from_env
from alphadb.paper.ioc import ApprovedOrderIntent, PaperExecutionRepository
from alphadb.runtime import RuntimeGuardDecision, evaluate_runtime_guard
from alphadb.state.repository import OperationalStateRepository


class LiveOrderError(RuntimeError):
    """Raised when a live order cannot be submitted safely."""


class KalshiLiveOrderClient(Protocol):
    def create_order(
        self,
        *,
        request_payload: Mapping[str, Any],
        settings: Settings,
    ) -> Mapping[str, Any]:
        """Submit a Kalshi order request and return the exchange response."""


class HttpKalshiLiveOrderClient:
    path = "/portfolio/events/orders"

    def create_order(
        self,
        *,
        request_payload: Mapping[str, Any],
        settings: Settings,
    ) -> Mapping[str, Any]:
        url = settings.kalshi_base_url.rstrip("/") + self.path
        body = json.dumps(request_payload).encode("utf-8")
        http_request = request.Request(
            url,
            data=body,
            headers=signed_kalshi_headers(
                settings=settings,
                method="POST",
                path=self.path,
            ),
            method="POST",
        )
        with request.urlopen(http_request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise LiveOrderError("Kalshi create-order response was not a JSON object")
        return payload


@dataclass(frozen=True)
class LiveOrderAttempt:
    live_order_attempt_id: str
    order_intent_id: str | None
    risk_decision_id: str | None
    market_ticker: str | None
    runtime_mode: str
    status: str
    guard_reason: str | None
    request_payload: Mapping[str, Any]
    response_payload: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "live_order_attempt_id": self.live_order_attempt_id,
            "order_intent_id": self.order_intent_id,
            "risk_decision_id": self.risk_decision_id,
            "market_ticker": self.market_ticker,
            "runtime_mode": self.runtime_mode,
            "status": self.status,
            "guard_reason": self.guard_reason,
            "request_payload": dict(self.request_payload),
            "response_payload": None if self.response_payload is None else dict(self.response_payload),
        }


class LiveOrderRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def persist(self, attempt: LiveOrderAttempt) -> LiveOrderAttempt:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into live_order_attempts (
                        live_order_attempt_id,
                        order_intent_id,
                        risk_decision_id,
                        market_ticker,
                        runtime_mode,
                        status,
                        guard_reason,
                        request_payload,
                        response_payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning live_order_attempt_id
                    """,
                    (
                        attempt.live_order_attempt_id,
                        attempt.order_intent_id,
                        attempt.risk_decision_id,
                        attempt.market_ticker,
                        attempt.runtime_mode,
                        attempt.status,
                        attempt.guard_reason,
                        Jsonb(dict(attempt.request_payload)),
                        None
                        if attempt.response_payload is None
                        else Jsonb(dict(attempt.response_payload)),
                    ),
                )
            connection.commit()
        return attempt

    def recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        live_order_attempt_id,
                        order_intent_id,
                        market_ticker,
                        runtime_mode,
                        status,
                        guard_reason,
                        request_payload,
                        response_payload,
                        created_at
                    from live_order_attempts
                    order by created_at desc, live_order_attempt_id desc
                    limit %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def accepted_max_cost_dollars(self, *, trading_day: date) -> float:
        day_start = datetime.combine(trading_day, datetime.min.time(), tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select coalesce(sum(oi.max_cost_dollars), 0)::float as accepted_max_cost
                    from live_order_attempts loa
                    join order_intents oi on oi.order_intent_id = loa.order_intent_id
                    where loa.status = 'accepted'
                      and loa.created_at >= %s
                      and loa.created_at < %s
                    """,
                    (day_start, day_end),
                )
                row = cursor.fetchone()
        return float(row["accepted_max_cost"] if row else 0.0)


class GatedLiveKalshiOrderAdapter:
    def __init__(
        self,
        *,
        database_url: str,
        client: KalshiLiveOrderClient | None = None,
    ):
        self.database_url = database_url
        self.client = client or HttpKalshiLiveOrderClient()
        self.paper_repository = PaperExecutionRepository(database_url)
        self.repository = LiveOrderRepository(database_url)

    def submit_order_intent(
        self,
        *,
        order_intent_id: str,
        settings: Settings | None = None,
    ) -> LiveOrderAttempt:
        settings = settings or settings_from_env()
        guard = evaluate_runtime_guard(settings)
        intent = self.paper_repository.get_approved_order_intent(order_intent_id)
        payload = kalshi_order_request_from_intent(intent)
        if not guard.can_submit_live_orders:
            attempt = attempt_from_guard(
                guard=guard,
                intent=intent,
                request_payload=payload,
                status="guard_denied",
            )
            self.repository.persist(attempt)
            raise LiveOrderError(f"live order denied: {guard.denial_reason}")
        response = self.client.create_order(request_payload=payload, settings=settings)
        status = "accepted" if exchange_response_accepted(response) else "rejected"
        attempt = LiveOrderAttempt(
            live_order_attempt_id=f"live_order_{uuid4().hex[:12]}",
            order_intent_id=intent.order_intent_id,
            risk_decision_id=intent.risk_decision_id,
            market_ticker=intent.market_ticker,
            runtime_mode=guard.runtime_mode.value,
            status=status,
            guard_reason=None,
            request_payload=payload,
            response_payload=response,
        )
        return self.repository.persist(attempt)


def kalshi_order_request_from_intent(intent: ApprovedOrderIntent) -> dict[str, Any]:
    side, yes_side_limit_price = kalshi_order_side_and_price(intent)
    return {
        "ticker": intent.market_ticker,
        "client_order_id": intent.order_intent_id,
        "side": side,
        "count": f"{float(intent.quantity):.2f}",
        "price": f"{yes_side_limit_price:.4f}",
        "time_in_force": "immediate_or_cancel",
        "post_only": False,
        "self_trade_prevention_type": "taker_at_cross",
        "cancel_order_on_pause": True,
    }


def kalshi_order_side_and_price(intent: ApprovedOrderIntent) -> tuple[str, float]:
    if intent.side == "yes":
        return "bid", intent.limit_price_dollars
    if intent.side == "no":
        return "ask", 1.0 - intent.limit_price_dollars
    raise LiveOrderError(f"unsupported order intent side: {intent.side}")


def signed_kalshi_headers(
    *,
    settings: Settings,
    method: str,
    path: str,
) -> dict[str, str]:
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        raise LiveOrderError("Kalshi live order request needs API key id and private key path")
    timestamp_ms = str(int(time.time() * 1000))
    root_path = urlparse(settings.kalshi_base_url).path.rstrip("/")
    full_path = f"{root_path}{path}"
    signature = sign_kalshi_request(
        private_key=load_private_key(settings.kalshi_private_key_path),
        timestamp_ms=timestamp_ms,
        method=method,
        path=full_path,
    )
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "alphadb/0.1",
        "KALSHI-ACCESS-KEY": settings.kalshi_api_key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


def load_private_key(path: str | Path) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(Path(path).expanduser().read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise LiveOrderError("Kalshi private key must be an RSA private key")
    return key


def sign_kalshi_request(
    *,
    private_key: rsa.RSAPrivateKey,
    timestamp_ms: str,
    method: str,
    path: str,
) -> str:
    signature = private_key.sign(
        f"{timestamp_ms}{method.upper()}{path}".encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def attempt_from_guard(
    *,
    guard: RuntimeGuardDecision,
    intent: ApprovedOrderIntent,
    request_payload: Mapping[str, Any],
    status: str,
) -> LiveOrderAttempt:
    return LiveOrderAttempt(
        live_order_attempt_id=f"live_order_{uuid4().hex[:12]}",
        order_intent_id=intent.order_intent_id,
        risk_decision_id=intent.risk_decision_id,
        market_ticker=intent.market_ticker,
        runtime_mode=guard.runtime_mode.value,
        status=status,
        guard_reason=guard.denial_reason,
        request_payload=request_payload,
    )


def exchange_response_accepted(response: Mapping[str, Any]) -> bool:
    if response.get("error"):
        return False
    order = response.get("order")
    if isinstance(order, Mapping):
        status = str(order.get("status") or "").lower()
        return status not in {"rejected", "canceled", "failed"}
    status = str(response.get("status") or "").lower()
    return status in {"accepted", "resting", "executed", "filled", "pending"}


def live_adapter_status_rows(settings: Settings | None = None) -> list[dict[str, str | bool]]:
    settings = settings or settings_from_env()
    guard = evaluate_runtime_guard(settings)
    return [
        {"metric": "live_adapter_runtime_mode", "value": guard.runtime_mode.value},
        {"metric": "live_adapter_ready", "value": guard.can_submit_live_orders},
        {"metric": "live_adapter_guard_reason", "value": guard.denial_reason or ""},
        {"metric": "kalshi_credentials_present", "value": guard.credentials_present},
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-live-orders")
    subparsers = parser.add_subparsers(dest="command", required=True)
    smoke = subparsers.add_parser("live-smoke", help="Submit one guarded live order smoke")
    smoke.add_argument("--order-intent-id", required=True)
    status = subparsers.add_parser("status", help="Show live adapter readiness and attempts")
    status.add_argument("--limit", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    if args.command == "live-smoke":
        if not settings.enable_live_order_smoke:
            raise LiveOrderError("ALPHADB_ENABLE_LIVE_ORDER_SMOKE=1 is required")
        attempt = GatedLiveKalshiOrderAdapter(database_url=settings.database_url).submit_order_intent(
            order_intent_id=args.order_intent_id,
            settings=settings,
        )
        print(json.dumps(attempt.as_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        print(
            json.dumps(
                {
                    "guard": live_adapter_status_rows(settings),
                    "recent_attempts": LiveOrderRepository(settings.database_url).recent(
                        limit=args.limit
                    ),
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
