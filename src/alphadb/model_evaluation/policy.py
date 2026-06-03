"""Clean holdout policy-selection reports for model evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from alphadb.model_evaluation.metrics import (
    calibration_buckets,
    optional_float,
    probability_metrics,
    simulate_policy,
    summarize_policy_metrics,
)


@dataclass(frozen=True)
class PolicyCandidate:
    candidate: str
    decision_minute_offset: int
    min_ev: float
    min_confidence: float
    sizing: str = "fixed_dollars"

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "decision_minute_offset": self.decision_minute_offset,
            "min_ev": self.min_ev,
            "min_confidence": self.min_confidence,
            "sizing": self.sizing,
        }


@dataclass(frozen=True)
class HoldoutSplit:
    selection_rows: tuple[dict[str, Any], ...]
    holdout_rows: tuple[dict[str, Any], ...]
    selection_markets: tuple[str, ...]
    holdout_markets: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "selection_rows": len(self.selection_rows),
            "holdout_rows": len(self.holdout_rows),
            "selection_market_count": len(self.selection_markets),
            "holdout_market_count": len(self.holdout_markets),
            "selection_markets": list(self.selection_markets),
            "holdout_markets": list(self.holdout_markets),
            "split_key": "ticker ordered by market_open_time/decision_timestamp",
        }


def build_holdout_policy_selection_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    selection_fraction: float = 0.5,
    min_ev_values: Sequence[float] = (0.0,),
    min_confidence_values: Sequence[float] = (0.0,),
    fixed_dollars_per_trade: float = 5.0,
    bankroll_dollars: float = 1000.0,
    taker_fee_multiplier: float = 0.07,
    worse_spread_cents: float = 1.0,
    fee_sensitivity_multiplier: float = 2.0,
    entry_delay_minutes: int = 1,
) -> dict[str, Any]:
    split = split_selection_holdout(rows, selection_fraction=selection_fraction)
    policies = enumerate_policy_candidates(
        split.selection_rows,
        min_ev_values=min_ev_values,
        min_confidence_values=min_confidence_values,
    )
    selection_reports: list[dict[str, Any]] = []
    for policy in policies:
        policy_rows = rows_for_policy(split.selection_rows, policy)
        metrics = simulate_policy(
            policy_rows,
            min_ev=policy.min_ev,
            min_confidence=policy.min_confidence,
            decision_minute_offset=policy.decision_minute_offset,
            fixed_dollars_per_trade=fixed_dollars_per_trade,
            bankroll_dollars=bankroll_dollars,
            taker_fee_multiplier=taker_fee_multiplier,
        )
        selection_reports.append(
            {
                "policy": policy.as_dict(),
                "split_role": "selection",
                "metrics": summarize_policy_metrics(metrics),
            }
        )
    selected = select_best_policy(selection_reports)
    holdout_rows = rows_for_policy(split.holdout_rows, selected)
    holdout_metrics = simulate_policy(
        holdout_rows,
        min_ev=selected.min_ev,
        min_confidence=selected.min_confidence,
        decision_minute_offset=selected.decision_minute_offset,
        fixed_dollars_per_trade=fixed_dollars_per_trade,
        bankroll_dollars=bankroll_dollars,
        taker_fee_multiplier=taker_fee_multiplier,
    )
    stress = build_stress_scenarios(
        split.holdout_rows,
        selected,
        fixed_dollars_per_trade=fixed_dollars_per_trade,
        bankroll_dollars=bankroll_dollars,
        taker_fee_multiplier=taker_fee_multiplier,
        worse_spread_cents=worse_spread_cents,
        fee_sensitivity_multiplier=fee_sensitivity_multiplier,
        entry_delay_minutes=entry_delay_minutes,
    )
    return {
        "schema_version": "kxbtc_model_holdout_policy_selection_v1",
        "split": split.as_dict(),
        "selected_policy": selected.as_dict(),
        "selection": selection_reports,
        "holdout": {
            "split_role": "holdout",
            "probability_metrics": probability_metrics(holdout_rows),
            "calibration": calibration_buckets(holdout_rows),
            "policy_metrics": summarize_policy_metrics(holdout_metrics),
        },
        "stress_scenarios": stress,
        "non_promotion_notice": (
            "This model evaluation report informs research only and does not authorize "
            "model promotion or live trading."
        ),
    }


def split_selection_holdout(
    rows: Sequence[Mapping[str, Any]],
    *,
    selection_fraction: float,
) -> HoldoutSplit:
    if not 0.0 < selection_fraction < 1.0:
        raise ValueError("selection_fraction must be between 0 and 1")
    sort_keys = market_sort_keys(rows)
    ordered_markets = sorted(sort_keys, key=lambda ticker: sort_keys[ticker])
    if len(ordered_markets) < 2:
        raise ValueError("at least two market tickers are required for holdout splitting")
    selection_count = max(1, int(len(ordered_markets) * selection_fraction))
    selection_count = min(selection_count, len(ordered_markets) - 1)
    selection_markets = tuple(ordered_markets[:selection_count])
    holdout_markets = tuple(ordered_markets[selection_count:])
    selection_set = set(selection_markets)
    holdout_set = set(holdout_markets)
    return HoldoutSplit(
        selection_rows=tuple(dict(row) for row in rows if str(row.get("ticker")) in selection_set),
        holdout_rows=tuple(dict(row) for row in rows if str(row.get("ticker")) in holdout_set),
        selection_markets=selection_markets,
        holdout_markets=holdout_markets,
    )


def market_sort_key(rows: Sequence[Mapping[str, Any]], ticker: str) -> tuple[str, str]:
    return market_sort_keys(rows).get(ticker, ("", ticker))


def market_sort_keys(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    keys: dict[str, tuple[str, str]] = {}
    for row in rows:
        ticker = row.get("ticker")
        if not ticker:
            continue
        ticker_text = str(ticker)
        timestamp = str(row.get("market_open_time") or row.get("decision_timestamp") or "")
        key = (timestamp, ticker_text)
        if ticker_text not in keys or key < keys[ticker_text]:
            keys[ticker_text] = key
    return keys


def enumerate_policy_candidates(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_ev_values: Sequence[float],
    min_confidence_values: Sequence[float],
) -> list[PolicyCandidate]:
    candidates = sorted({str(row.get("candidate")) for row in rows if row.get("candidate")})
    offsets = sorted(
        {
            int(value)
            for value in (optional_float(row.get("decision_minute_offset")) for row in rows)
            if value is not None
        }
    )
    return [
        PolicyCandidate(
            candidate=candidate,
            decision_minute_offset=offset,
            min_ev=float(min_ev),
            min_confidence=float(min_confidence),
        )
        for candidate in candidates
        for offset in offsets
        for min_ev in min_ev_values
        for min_confidence in min_confidence_values
    ]


def rows_for_policy(rows: Sequence[Mapping[str, Any]], policy: PolicyCandidate) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if str(row.get("candidate")) == policy.candidate]


def select_best_policy(selection_reports: Sequence[Mapping[str, Any]]) -> PolicyCandidate:
    passing = [
        report
        for report in selection_reports
        if int(report["metrics"].get("trade_count") or 0) > 0
        and report["metrics"].get("expected_log_growth") is not None
    ]
    if not passing:
        raise ValueError("no policy candidates produced trades on the selection split")
    best = max(
        passing,
        key=lambda report: (
            float(report["metrics"].get("expected_log_growth") or float("-inf")),
            float(report["metrics"].get("net_pnl") or float("-inf")),
            -float(report["metrics"].get("max_drawdown") or float("inf")),
        ),
    )
    payload = best["policy"]
    return PolicyCandidate(
        candidate=str(payload["candidate"]),
        decision_minute_offset=int(payload["decision_minute_offset"]),
        min_ev=float(payload["min_ev"]),
        min_confidence=float(payload["min_confidence"]),
        sizing=str(payload.get("sizing", "fixed_dollars")),
    )


def build_stress_scenarios(
    rows: Sequence[Mapping[str, Any]],
    policy: PolicyCandidate,
    *,
    fixed_dollars_per_trade: float,
    bankroll_dollars: float,
    taker_fee_multiplier: float,
    worse_spread_cents: float,
    fee_sensitivity_multiplier: float,
    entry_delay_minutes: int,
) -> list[dict[str, Any]]:
    scenarios = [
        (
            "base_holdout",
            policy.decision_minute_offset,
            taker_fee_multiplier,
            0.0,
        ),
        (
            f"worse_spread_{worse_spread_cents:g}_cents",
            policy.decision_minute_offset,
            taker_fee_multiplier,
            worse_spread_cents,
        ),
        (
            f"fees_x_{fee_sensitivity_multiplier:g}",
            policy.decision_minute_offset,
            taker_fee_multiplier * fee_sensitivity_multiplier,
            0.0,
        ),
        (
            f"entry_delay_{entry_delay_minutes}_minutes",
            policy.decision_minute_offset + entry_delay_minutes,
            taker_fee_multiplier,
            0.0,
        ),
    ]
    output = []
    for name, offset, fee_multiplier, spread in scenarios:
        metrics = simulate_policy(
            rows_for_policy(rows, policy),
            min_ev=policy.min_ev,
            min_confidence=policy.min_confidence,
            decision_minute_offset=offset,
            fixed_dollars_per_trade=fixed_dollars_per_trade,
            bankroll_dollars=bankroll_dollars,
            taker_fee_multiplier=fee_multiplier,
            extra_spread_cents=spread,
        )
        output.append(
            {
                "name": name,
                "split_role": "holdout_stress",
                "decision_minute_offset": offset,
                "metrics": summarize_policy_metrics(metrics),
            }
        )
    return output
