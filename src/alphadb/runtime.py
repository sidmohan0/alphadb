"""Runtime-mode contract for live order enablement."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from alphadb.config import Settings, settings_from_env
from alphadb.live_runtime import (
    FAIR_VALUE_LIVE_STRATEGY,
    LiveRuntimeConfig,
    LiveRuntimeConfigRepository,
    validate_market_context_source,
)


class RuntimeMode(StrEnum):
    FIXTURE = "fixture"
    SHADOW = "shadow"
    PAPER = "paper"
    GATED_LIVE = "gated-live"


class RuntimeGuardError(ValueError):
    """Raised when runtime/live configuration is unsupported or unsafe."""


@dataclass(frozen=True)
class RuntimeGuardDecision:
    runtime_mode: RuntimeMode
    live_enabled: bool
    can_submit_live_orders: bool
    denial_reason: str | None
    paper_orders_allowed: bool
    credentials_present: bool
    human_cutover_approved: bool
    explicit_live_enabled: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_mode": self.runtime_mode.value,
            "live_enabled": self.live_enabled,
            "can_submit_live_orders": self.can_submit_live_orders,
            "denial_reason": self.denial_reason,
            "paper_orders_allowed": self.paper_orders_allowed,
            "credentials_present": self.credentials_present,
            "human_cutover_approved": self.human_cutover_approved,
            "explicit_live_enabled": self.explicit_live_enabled,
        }


def parse_runtime_mode(value: str) -> RuntimeMode:
    try:
        return RuntimeMode(value)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in RuntimeMode)
        raise RuntimeGuardError(f"unsupported runtime mode {value!r}; expected one of {allowed}") from exc


def evaluate_runtime_guard(settings: Settings | None = None) -> RuntimeGuardDecision:
    settings = settings or settings_from_env()
    mode = parse_runtime_mode(settings.runtime_mode)
    credentials_present = bool(settings.kalshi_api_key_id and settings.kalshi_private_key_path)
    explicit_live = settings.enable_live_orders

    if mode in (RuntimeMode.FIXTURE, RuntimeMode.SHADOW):
        reason = f"runtime_mode_{mode.value.replace('-', '_')}_disables_live_orders"
        if explicit_live:
            reason = "live_enabled_outside_gated_live"
        return RuntimeGuardDecision(
            runtime_mode=mode,
            live_enabled=False,
            can_submit_live_orders=False,
            denial_reason=reason,
            paper_orders_allowed=False,
            credentials_present=credentials_present,
            human_cutover_approved=settings.human_cutover_approved,
            explicit_live_enabled=explicit_live,
        )

    if mode == RuntimeMode.PAPER:
        reason = "paper_mode_disables_live_orders"
        if explicit_live:
            reason = "live_enabled_outside_gated_live"
        return RuntimeGuardDecision(
            runtime_mode=mode,
            live_enabled=False,
            can_submit_live_orders=False,
            denial_reason=reason,
            paper_orders_allowed=True,
            credentials_present=credentials_present,
            human_cutover_approved=settings.human_cutover_approved,
            explicit_live_enabled=explicit_live,
        )

    if not explicit_live:
        reason = "live_orders_not_explicitly_enabled"
    elif not credentials_present:
        reason = "missing_kalshi_credentials"
    elif not settings.human_cutover_approved:
        reason = "missing_human_cutover_approval"
    else:
        reason = None

    return RuntimeGuardDecision(
        runtime_mode=mode,
        live_enabled=reason is None,
        can_submit_live_orders=reason is None,
        denial_reason=reason,
        paper_orders_allowed=False,
        credentials_present=credentials_present,
        human_cutover_approved=settings.human_cutover_approved,
        explicit_live_enabled=explicit_live,
    )


def runtime_status_rows(settings: Settings | None = None) -> list[dict[str, str | bool]]:
    decision = evaluate_runtime_guard(settings)
    return [
        {"metric": "mode", "value": decision.runtime_mode.value},
        {"metric": "live_order_submission_enabled", "value": decision.live_enabled},
        {"metric": "can_submit_live_orders", "value": decision.can_submit_live_orders},
        {"metric": "simulator_orders_allowed", "value": decision.paper_orders_allowed},
        {"metric": "live_order_block_reason", "value": decision.denial_reason or ""},
        {"metric": "kalshi_credentials_present", "value": decision.credentials_present},
        {"metric": "operator_live_approval", "value": decision.human_cutover_approved},
    ]


def live_config_status(
    *,
    settings: Settings | None = None,
    strategy: str = FAIR_VALUE_LIVE_STRATEGY,
) -> dict[str, Any]:
    settings = settings or settings_from_env()
    active = LiveRuntimeConfigRepository(settings.database_url).get_active_config(
        strategy=strategy,
    )
    if active is None:
        return {
            "ok": False,
            "detail": "no active live runtime config",
            "strategy": strategy,
        }
    return {
        "ok": True,
        "detail": "active live runtime config is readable",
        "strategy": strategy,
        "active_config": active.as_dict(),
        "manifest_snapshot": active.manifest_snapshot(),
    }


def set_market_context_source(
    *,
    source: str,
    settings: Settings | None = None,
    strategy: str = FAIR_VALUE_LIVE_STRATEGY,
    created_by: str = "alphadb-runtime",
) -> dict[str, Any]:
    validate_market_context_source(source)
    settings = settings or settings_from_env()
    repository = LiveRuntimeConfigRepository(settings.database_url)
    current = repository.seed_defaults(strategy=strategy, created_by=created_by)
    next_config = LiveRuntimeConfig.from_payload(
        {"market_context_source": source},
        current=current.config,
    )
    if current.config.market_context_source == source:
        return {
            "ok": True,
            "detail": "market_context_source already active",
            "strategy": strategy,
            "action": "unchanged",
            "previous_config": current.as_dict(),
            "active_config": current.as_dict(),
            "manifest_snapshot": current.manifest_snapshot(),
        }
    saved = repository.save_config(next_config, strategy=strategy, created_by=created_by)
    return {
        "ok": True,
        "detail": "market_context_source saved",
        "strategy": strategy,
        "action": "saved",
        "previous_config": current.as_dict(),
        "active_config": saved.as_dict(),
        "manifest_snapshot": saved.manifest_snapshot(),
    }


def settings_with_overrides(settings: Settings, overrides: Mapping[str, Any]) -> Settings:
    values = {**settings.__dict__, **dict(overrides)}
    return Settings(**values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show runtime and live-order status")
    live_config = subparsers.add_parser(
        "live-config-status",
        help="Show the active dashboard-owned live runtime config",
    )
    live_config.add_argument("--strategy", default=FAIR_VALUE_LIVE_STRATEGY)
    market_context = subparsers.add_parser(
        "set-market-context",
        help="Save a new fair-value live runtime config with the selected market context",
    )
    market_context.add_argument("--source", required=True)
    market_context.add_argument("--strategy", default=FAIR_VALUE_LIVE_STRATEGY)
    market_context.add_argument("--created-by", default="alphadb-runtime")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        print(json.dumps(evaluate_runtime_guard().as_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "live-config-status":
        print(
            json.dumps(
                live_config_status(strategy=args.strategy),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "set-market-context":
        print(
            json.dumps(
                set_market_context_source(
                    source=args.source,
                    strategy=args.strategy,
                    created_by=args.created_by,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
