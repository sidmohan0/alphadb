"""Fair-value replay and walk-forward reports for fast strategy iteration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from alphadb.model_evaluation.metrics import max_drawdown, optional_float, taker_fee
from alphadb.model_evaluation.policy import market_sort_keys

Side = Literal["yes", "no"]

FAIR_VALUE_REPLAY_SCHEMA = "kxbtc_fair_value_replay_report.v1"
FAIR_VALUE_WALK_FORWARD_SCHEMA = "kxbtc_fair_value_walk_forward_report.v1"


@dataclass(frozen=True)
class FairValueReplayConfig:
    probability_column: str = "p_yes"
    min_edge: float = 0.0
    max_order_dollars: float = 5.0
    max_loss_dollars: float = 50.0
    taker_fee_multiplier: float = 0.07
    include_unsettled_orders: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "probability_column": self.probability_column,
            "min_edge": self.min_edge,
            "max_order_dollars": self.max_order_dollars,
            "max_loss_dollars": self.max_loss_dollars,
            "taker_fee_multiplier": self.taker_fee_multiplier,
            "include_unsettled_orders": self.include_unsettled_orders,
        }


def build_fair_value_replay_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: FairValueReplayConfig | None = None,
) -> dict[str, Any]:
    config = config or FairValueReplayConfig()
    normalized = [dict(row) for row in rows]
    decisions: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    cumulative_pnl = 0.0
    equity_curve = [0.0]
    skipped_reasons: Counter[str] = Counter()

    for row in sorted(normalized, key=replay_sort_key):
        decision = decide_trade(row, config=config, cumulative_pnl=cumulative_pnl)
        decisions.append(decision)
        if decision["decision"] != "trade":
            skipped_reasons[str(decision["reason"])] += 1
            continue
        orders.append(decision)
        if int(decision["filled_contracts"]) <= 0:
            skipped_reasons[str(decision["fill_status"])] += 1
            continue
        trades.append(decision)
        if decision["settlement_status"] == "settled":
            cumulative_pnl += float(decision["pnl_dollars"])
            equity_curve.append(cumulative_pnl)

    settled_trades = [trade for trade in trades if trade["settlement_status"] == "settled"]
    unsettled_trades = [trade for trade in trades if trade["settlement_status"] != "settled"]
    wins = [trade for trade in settled_trades if float(trade["pnl_dollars"]) > 0]
    losses = [trade for trade in settled_trades if float(trade["pnl_dollars"]) < 0]
    by_side = summarize_group(trades, "side")
    by_ticker = summarize_group(trades, "ticker")
    pnl = {
        "settled_trade_count": len(settled_trades),
        "unsettled_trade_count": len(unsettled_trades),
        "net_pnl_dollars": round(sum(float(trade["pnl_dollars"]) for trade in settled_trades), 6),
        "gross_cost_dollars": round(sum(float(trade["cost_dollars"]) for trade in trades), 6),
        "fees_dollars": round(sum(float(trade["fees_dollars"]) for trade in trades), 6),
        "payout_dollars": round(sum(float(trade["payout_dollars"]) for trade in settled_trades), 6),
        "unsettled_exposure_dollars": round(
            sum(float(trade["max_loss_dollars"]) for trade in unsettled_trades),
            6,
        ),
        "win_rate": len(wins) / len(settled_trades) if settled_trades else 0.0,
        "profit_factor": (
            sum(float(trade["pnl_dollars"]) for trade in wins)
            / abs(sum(float(trade["pnl_dollars"]) for trade in losses))
            if losses
            else None
        ),
        "max_drawdown_dollars": round(max_drawdown_dollars(equity_curve), 6),
        "max_drawdown": max_drawdown([value + config.max_loss_dollars for value in equity_curve]),
    }
    return {
        "schema_version": FAIR_VALUE_REPLAY_SCHEMA,
        "config": config.as_dict(),
        "input_rows": len(normalized),
        "counts": {
            "decisions": len(decisions),
            "orders": len(orders),
            "trades": len(trades),
            "filled_trades": len(trades),
            "unfilled_orders": len(orders) - len(trades),
            "settled_trades": len(settled_trades),
            "unsettled_trades": len(unsettled_trades),
            "skipped": len([decision for decision in decisions if decision["decision"] != "trade"]),
            "tickers": len({str(row.get("ticker") or row.get("market_ticker")) for row in normalized}),
        },
        "pnl": pnl,
        "settlement": {
            "status": settlement_status(settled_trades, unsettled_trades),
            "settled_rows": len(settled_trades),
            "unsettled_rows": len(unsettled_trades),
            "missing_or_delayed_rows": len(unsettled_trades),
            "unsettled_exposure_dollars": pnl["unsettled_exposure_dollars"],
            "default_reporting": "pnl_and_settlement_included",
        },
        "controls": {
            "max_order_dollars": config.max_order_dollars,
            "max_loss_dollars": config.max_loss_dollars,
            "loss_cap_reached": any(decision["reason"] == "loss_cap_reached" for decision in decisions),
        },
        "skips": skipped_reasons.most_common(),
        "breakdowns": {
            "by_side": by_side,
            "by_ticker": by_ticker[:25],
        },
        "orders": orders,
        "trades": trades,
        "decisions": decisions,
    }


def build_fair_value_walk_forward_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    selection_market_count: int,
    holdout_market_count: int,
    step_market_count: int | None = None,
    min_edge_values: Sequence[float] = (0.0,),
    max_order_dollars: float = 5.0,
    max_loss_dollars: float = 50.0,
    probability_column: str = "p_yes",
    taker_fee_multiplier: float = 0.07,
) -> dict[str, Any]:
    if selection_market_count < 1 or holdout_market_count < 1:
        raise ValueError("selection and holdout market counts must be positive")
    step = step_market_count or holdout_market_count
    ordered_markets = ordered_market_tickers(rows)
    windows = []
    start = 0
    while start + selection_market_count + holdout_market_count <= len(ordered_markets):
        selection_markets = tuple(ordered_markets[start : start + selection_market_count])
        holdout_markets = tuple(
            ordered_markets[
                start + selection_market_count : start + selection_market_count + holdout_market_count
            ]
        )
        selection_rows = rows_for_markets(rows, selection_markets)
        holdout_rows = rows_for_markets(rows, holdout_markets)
        candidates = []
        for edge in min_edge_values:
            candidate_config = FairValueReplayConfig(
                probability_column=probability_column,
                min_edge=float(edge),
                max_order_dollars=max_order_dollars,
                max_loss_dollars=max_loss_dollars,
                taker_fee_multiplier=taker_fee_multiplier,
            )
            candidate_report = build_fair_value_replay_report(selection_rows, config=candidate_config)
            candidates.append(
                {
                    "min_edge": float(edge),
                    "selection_pnl": candidate_report["pnl"]["net_pnl_dollars"],
                    "selection_trades": candidate_report["counts"]["trades"],
                    "selection_report": candidate_report,
                }
            )
        selected = select_walk_forward_candidate(candidates)
        selected_config = FairValueReplayConfig(
            probability_column=probability_column,
            min_edge=float(selected["min_edge"]),
            max_order_dollars=max_order_dollars,
            max_loss_dollars=max_loss_dollars,
            taker_fee_multiplier=taker_fee_multiplier,
        )
        holdout_report = build_fair_value_replay_report(holdout_rows, config=selected_config)
        windows.append(
            {
                "window_index": len(windows),
                "selection_markets": list(selection_markets),
                "holdout_markets": list(holdout_markets),
                "selected_min_edge": selected["min_edge"],
                "selection": {
                    "candidate_count": len(candidates),
                    "best_pnl": selected["selection_pnl"],
                    "best_trades": selected["selection_trades"],
                    "candidates": [
                        {
                            "min_edge": candidate["min_edge"],
                            "selection_pnl": candidate["selection_pnl"],
                            "selection_trades": candidate["selection_trades"],
                        }
                        for candidate in candidates
                    ],
                },
                "holdout": {
                    "trades": holdout_report["counts"]["trades"],
                    "settled_trades": holdout_report["counts"]["settled_trades"],
                    "unsettled_trades": holdout_report["counts"]["unsettled_trades"],
                    "skipped": holdout_report["counts"]["skipped"],
                    "skip_reasons": holdout_report["skips"],
                    "net_pnl_dollars": holdout_report["pnl"]["net_pnl_dollars"],
                    "unsettled_exposure_dollars": holdout_report["pnl"][
                        "unsettled_exposure_dollars"
                    ],
                    "win_rate": holdout_report["pnl"]["win_rate"],
                    "fees_dollars": holdout_report["pnl"]["fees_dollars"],
                    "settlement_status": holdout_report["settlement"]["status"],
                    "settlement": holdout_report["settlement"],
                },
            }
        )
        start += step
    return {
        "schema_version": FAIR_VALUE_WALK_FORWARD_SCHEMA,
        "config": {
            "selection_market_count": selection_market_count,
            "holdout_market_count": holdout_market_count,
            "step_market_count": step,
            "min_edge_values": [float(value) for value in min_edge_values],
            "max_order_dollars": max_order_dollars,
            "max_loss_dollars": max_loss_dollars,
            "probability_column": probability_column,
            "taker_fee_multiplier": taker_fee_multiplier,
        },
        "market_count": len(ordered_markets),
        "complete_window_count": len(windows),
        "aggregate": {
            "holdout_net_pnl_dollars": round(
                sum(float(window["holdout"]["net_pnl_dollars"]) for window in windows), 6
            ),
            "holdout_trade_count": sum(int(window["holdout"]["trades"]) for window in windows),
            "selected_min_edge_counts": Counter(
                str(window["selected_min_edge"]) for window in windows
            ),
        },
        "windows": windows,
    }


def decide_trade(
    row: Mapping[str, Any],
    *,
    config: FairValueReplayConfig,
    cumulative_pnl: float,
) -> dict[str, Any]:
    base = {
        "ticker": str(row.get("ticker") or row.get("market_ticker") or ""),
        "decision_timestamp": row.get("decision_timestamp") or row.get("timestamp"),
    }
    p_yes = optional_float(row.get(config.probability_column))
    yes_ask = first_float(row, ("yes_ask", "yes_ask_dollars", "executable_yes_price"))
    no_ask = first_float(row, ("no_ask", "no_ask_dollars", "executable_no_price"))
    result = result_side(row)
    if p_yes is None:
        return {**base, "decision": "skip", "reason": "missing_fair_value"}
    if yes_ask is None or no_ask is None:
        return {**base, "decision": "skip", "reason": "missing_executable_price"}
    if not 0.0 <= p_yes <= 1.0:
        return {**base, "decision": "skip", "reason": "invalid_fair_value"}
    yes = side_ev("yes", p_yes, yes_ask, config.taker_fee_multiplier)
    no = side_ev("no", p_yes, no_ask, config.taker_fee_multiplier)
    choice = yes if yes["edge"] >= no["edge"] else no
    if float(choice["edge"]) < config.min_edge:
        return {**base, "decision": "skip", "reason": "edge_below_min", **choice}
    remaining_loss = max(0.0, config.max_loss_dollars + min(0.0, cumulative_pnl))
    if remaining_loss <= 0:
        return {**base, "decision": "skip", "reason": "loss_cap_reached", **choice}
    per_contract_loss = float(choice["price"]) + float(choice["fee"])
    order_cap_contracts = int(config.max_order_dollars // max(per_contract_loss, 0.01))
    loss_cap_contracts = int(remaining_loss // max(per_contract_loss, 0.01))
    if loss_cap_contracts <= 0:
        return {**base, "decision": "skip", "reason": "loss_cap_reached", **choice}
    intended_contracts = max(0, min(order_cap_contracts, loss_cap_contracts))
    if intended_contracts <= 0:
        return {**base, "decision": "skip", "reason": "order_cap_too_small", **choice}
    filled_contracts = filled_contract_count(row, intended_contracts)
    settled = result in {"yes", "no"}
    payout_per_contract = 1.0 if settled and result == choice["side"] else 0.0
    cost = float(choice["price"]) * filled_contracts
    fees = float(choice["fee"]) * filled_contracts
    payout = payout_per_contract * filled_contracts if settled else 0.0
    pnl = payout - cost - fees if settled else 0.0
    max_loss = cost + fees
    return {
        **base,
        "decision": "trade",
        "reason": "edge_met",
        "order_type": "simulated_taker_ioc",
        "order_status": "filled" if filled_contracts == intended_contracts else "partial_or_unfilled",
        "fill_status": fill_status(filled_contracts, intended_contracts),
        "settlement_status": "settled" if settled else "unsettled",
        "result": result,
        "side": choice["side"],
        "fair_value": choice["probability"],
        "price": choice["price"],
        "fee_per_contract": choice["fee"],
        "edge": choice["edge"],
        "intended_contracts": intended_contracts,
        "filled_contracts": filled_contracts,
        "contracts": filled_contracts,
        "cost_dollars": round(cost, 6),
        "fees_dollars": round(fees, 6),
        "payout_dollars": round(payout, 6),
        "pnl_dollars": round(pnl, 6),
        "max_loss_dollars": round(max_loss, 6),
    }


def side_ev(side: Side, p_yes: float, price: float, fee_multiplier: float) -> dict[str, Any]:
    probability = p_yes if side == "yes" else 1.0 - p_yes
    fee = taker_fee(price, fee_multiplier)
    return {
        "side": side,
        "probability": probability,
        "price": price,
        "fee": fee,
        "edge": probability - price - fee,
    }


def first_float(row: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = optional_float(row.get(key))
        if value is not None:
            return value
    return None


def filled_contract_count(row: Mapping[str, Any], intended_contracts: int) -> int:
    status = str(row.get("fill_status") or row.get("order_status") or "").strip().lower()
    if status in {"unfilled", "not_filled", "canceled", "cancelled", "expired"}:
        return 0
    explicit = first_float(
        row,
        ("filled_contracts", "fill_contracts", "executed_contracts", "fill_quantity"),
    )
    if explicit is None:
        return intended_contracts
    return max(0, min(int(explicit), intended_contracts))


def fill_status(filled_contracts: int, intended_contracts: int) -> str:
    if filled_contracts <= 0:
        return "unfilled"
    if filled_contracts < intended_contracts:
        return "partial_fill"
    return "filled"


def result_side(row: Mapping[str, Any]) -> str | None:
    raw = row.get("market_result") or row.get("result") or row.get("settlement_result")
    if raw is None:
        yes = optional_float(row.get("yes"))
        if yes in (0.0, 1.0):
            return "yes" if yes == 1.0 else "no"
        return None
    text = str(raw).strip().lower()
    if text in {"yes", "y", "1", "true"}:
        return "yes"
    if text in {"no", "n", "0", "false"}:
        return "no"
    return None


def replay_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    timestamp = row.get("decision_timestamp") or row.get("timestamp") or row.get("market_open_time") or ""
    return str(timestamp), str(row.get("ticker") or row.get("market_ticker") or "")


def summarize_group(trades: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    output = []
    for value in sorted({str(trade.get(key)) for trade in trades}):
        group = [trade for trade in trades if str(trade.get(key)) == value]
        output.append(
            {
                key: value,
                "trades": len(group),
                "settled_trades": sum(1 for trade in group if trade["settlement_status"] == "settled"),
                "unsettled_trades": sum(
                    1 for trade in group if trade["settlement_status"] != "settled"
                ),
                "net_pnl_dollars": round(sum(float(trade["pnl_dollars"]) for trade in group), 6),
                "fees_dollars": round(sum(float(trade["fees_dollars"]) for trade in group), 6),
                "unsettled_exposure_dollars": round(
                    sum(
                        float(trade["max_loss_dollars"])
                        for trade in group
                        if trade["settlement_status"] != "settled"
                    ),
                    6,
                ),
            }
        )
    return output


def settlement_status(
    settled_trades: Sequence[Mapping[str, Any]],
    unsettled_trades: Sequence[Mapping[str, Any]],
) -> str:
    if unsettled_trades and settled_trades:
        return "partial"
    if unsettled_trades:
        return "unreconciled"
    return "reconciled"


def max_drawdown_dollars(equity_curve: Sequence[float]) -> float:
    peak = equity_curve[0] if equity_curve else 0.0
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return abs(worst)


def ordered_market_tickers(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    sort_keys = market_sort_keys(rows)
    if sort_keys:
        return sorted(sort_keys, key=lambda ticker: sort_keys[ticker])
    return sorted({str(row.get("ticker") or row.get("market_ticker")) for row in rows})


def rows_for_markets(
    rows: Sequence[Mapping[str, Any]],
    market_tickers: Sequence[str],
) -> list[dict[str, Any]]:
    tickers = set(market_tickers)
    return [dict(row) for row in rows if str(row.get("ticker") or row.get("market_ticker")) in tickers]


def select_walk_forward_candidate(candidates: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not candidates:
        raise ValueError("at least one min_edge candidate is required")
    return max(
        candidates,
        key=lambda candidate: (
            float(candidate["selection_pnl"]),
            int(candidate["selection_trades"]),
            -float(candidate["min_edge"]),
        ),
    )


def parse_min_edge_values(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
