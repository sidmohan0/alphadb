"""Probability and policy metrics for KXBTC15M model evaluation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

Side = Literal["yes", "no"]


@dataclass(frozen=True)
class TradeDecision:
    ticker: str
    decision_minute_offset: int
    selected_side: Side
    side_price: float
    side_fee: float
    side_ev: float
    probability: float
    yes: int
    contracts: int
    pnl: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "decision_minute_offset": self.decision_minute_offset,
            "selected_side": self.selected_side,
            "side_price": self.side_price,
            "side_fee": self.side_fee,
            "side_ev": self.side_ev,
            "probability": self.probability,
            "yes": self.yes,
            "contracts": self.contracts,
            "pnl": self.pnl,
        }


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def required_float(row: Mapping[str, Any], key: str) -> float:
    value = optional_float(row.get(key))
    if value is None:
        raise ValueError(f"row missing numeric {key!r}")
    return value


def required_int(row: Mapping[str, Any], key: str) -> int:
    value = optional_float(row.get(key))
    if value is None:
        raise ValueError(f"row missing integer {key!r}")
    return int(value)


def taker_fee(price: float, multiplier: float = 0.07) -> float:
    return float(multiplier) * float(price) * (1.0 - float(price))


def max_drawdown(equity_curve: Sequence[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = float(equity_curve[0])
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, float(value))
        if peak > 0:
            worst = min(worst, (float(value) - peak) / peak)
    return abs(worst)


def probability_metrics(rows: Sequence[Mapping[str, Any]], *, probability_column: str = "p_yes") -> dict[str, Any]:
    pairs: list[tuple[int, float]] = []
    for row in rows:
        yes = optional_float(row.get("yes"))
        probability = optional_float(row.get(probability_column))
        if yes in (0.0, 1.0) and probability is not None:
            pairs.append((int(yes), min(max(probability, 1e-6), 1.0 - 1e-6)))
    if not pairs:
        return {
            "rows": 0,
            "brier": None,
            "brier_score": None,
            "log_loss": None,
            "accuracy_50": None,
            "mean_probability": None,
            "positive_rate": None,
            "roc_auc": None,
            "average_precision": None,
        }
    count = len(pairs)
    brier = sum((probability - yes) ** 2 for yes, probability in pairs) / count
    log_loss = -sum(
        yes * math.log(probability) + (1 - yes) * math.log(1.0 - probability)
        for yes, probability in pairs
    ) / count
    accuracy = sum(1 for yes, probability in pairs if int(probability >= 0.5) == yes) / count
    mean_probability = sum(probability for _yes, probability in pairs) / count
    labels = [yes for yes, _probability in pairs]
    probabilities = [probability for _yes, probability in pairs]
    roc_auc = None
    average_precision = None
    positive_rate = sum(labels) / count
    if len(set(labels)) == 2:
        try:
            from sklearn.metrics import average_precision_score, roc_auc_score

            roc_auc = float(roc_auc_score(labels, probabilities))
            average_precision = float(average_precision_score(labels, probabilities))
        except Exception:
            roc_auc = None
            average_precision = None
    return {
        "rows": count,
        "brier": brier,
        "brier_score": brier,
        "log_loss": log_loss,
        "accuracy_50": accuracy,
        "mean_probability": mean_probability,
        "positive_rate": positive_rate,
        "roc_auc": roc_auc,
        "average_precision": average_precision,
    }


def calibration_buckets(
    rows: Sequence[Mapping[str, Any]],
    *,
    probability_column: str = "p_yes",
    bins: int = 10,
) -> dict[str, Any]:
    buckets: list[list[tuple[int, float]]] = [[] for _ in range(bins)]
    total = 0
    for row in rows:
        yes = optional_float(row.get("yes"))
        probability = optional_float(row.get(probability_column))
        if yes not in (0.0, 1.0) or probability is None:
            continue
        clipped = min(max(probability, 1e-6), 1.0 - 1e-6)
        index = min(bins - 1, max(0, int(clipped * bins)))
        buckets[index].append((int(yes), clipped))
        total += 1

    rows_out: list[dict[str, Any]] = []
    ece = 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        count = len(bucket)
        mean_probability = sum(probability for _yes, probability in bucket) / count
        observed_yes_rate = sum(yes for yes, _probability in bucket) / count
        if total:
            ece += (count / total) * abs(mean_probability - observed_yes_rate)
        rows_out.append(
            {
                "bucket": index,
                "count": count,
                "mean_probability": mean_probability,
                "observed_yes_rate": observed_yes_rate,
            }
        )
    return {"expected_calibration_error": ece, "buckets": rows_out}


def side_choice(
    row: Mapping[str, Any],
    *,
    probability_column: str = "p_yes",
    taker_fee_multiplier: float = 0.07,
) -> dict[str, Any] | None:
    probability_yes = optional_float(row.get(probability_column))
    yes_ask = optional_float(row.get("yes_ask"))
    no_ask = optional_float(row.get("no_ask"))
    yes = optional_float(row.get("yes"))
    if probability_yes is None or yes_ask is None or no_ask is None or yes not in (0.0, 1.0):
        return None
    if not (0.0 < yes_ask < 1.0 and 0.0 < no_ask < 1.0 and 0.0 <= probability_yes <= 1.0):
        return None
    yes_fee = optional_float(row.get("yes_fee"))
    no_fee = optional_float(row.get("no_fee"))
    yes_fee = taker_fee(yes_ask, taker_fee_multiplier) if yes_fee is None else yes_fee
    no_fee = taker_fee(no_ask, taker_fee_multiplier) if no_fee is None else no_fee
    yes_ev = probability_yes - yes_ask - yes_fee
    no_probability = 1.0 - probability_yes
    no_ev = no_probability - no_ask - no_fee
    if yes_ev >= no_ev:
        return {
            "side": "yes",
            "probability": probability_yes,
            "side_price": yes_ask,
            "side_fee": yes_fee,
            "side_ev": yes_ev,
            "yes": int(yes),
        }
    return {
        "side": "no",
        "probability": no_probability,
        "side_price": no_ask,
        "side_fee": no_fee,
        "side_ev": no_ev,
        "yes": int(yes),
    }


def simulate_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    probability_column: str = "p_yes",
    min_ev: float = 0.0,
    min_confidence: float = 0.0,
    decision_minute_offset: int | None = None,
    bankroll_dollars: float = 1000.0,
    fixed_dollars_per_trade: float = 5.0,
    fixed_contracts: int = 1,
    sizing: Literal["fixed_dollars", "fixed_contracts"] = "fixed_dollars",
    taker_fee_multiplier: float = 0.07,
    extra_spread_cents: float = 0.0,
    recompute_fees: bool = False,
) -> dict[str, Any]:
    equity = float(bankroll_dollars)
    equity_curve = [equity]
    trades: list[TradeDecision] = []
    skipped_count = 0
    executable_count = 0

    ordered = sorted(
        rows,
        key=lambda row: (
            int(optional_float(row.get("decision_minute_offset")) or -1),
            str(row.get("ticker", "")),
        ),
    )
    spread = extra_spread_cents / 100.0
    for row in ordered:
        row_offset = optional_float(row.get("decision_minute_offset"))
        if row_offset is None:
            skipped_count += 1
            continue
        if decision_minute_offset is not None and int(row_offset) != int(decision_minute_offset):
            continue
        adjusted = dict(row)
        if spread:
            for column in ("yes_ask", "no_ask"):
                value = optional_float(adjusted.get(column))
                if value is not None:
                    adjusted[column] = min(value + spread, 0.99)
        if spread or recompute_fees:
            adjusted.pop("yes_fee", None)
            adjusted.pop("no_fee", None)
        choice = side_choice(
            adjusted,
            probability_column=probability_column,
            taker_fee_multiplier=taker_fee_multiplier,
        )
        if choice is None:
            skipped_count += 1
            continue
        executable_count += 1
        if float(choice["side_ev"]) < min_ev or float(choice["probability"]) < min_confidence:
            skipped_count += 1
            continue
        if sizing == "fixed_contracts":
            contracts = max(0, int(fixed_contracts))
        else:
            contracts = max(0, int(float(fixed_dollars_per_trade) // max(choice["side_price"], 0.01)))
        if contracts <= 0:
            skipped_count += 1
            continue
        payout = choice["yes"] if choice["side"] == "yes" else 1 - choice["yes"]
        fee_total = float(choice["side_fee"]) * contracts
        pnl = (payout - float(choice["side_price"])) * contracts - fee_total
        equity += pnl
        equity_curve.append(equity)
        trades.append(
            TradeDecision(
                ticker=str(row.get("ticker", "")),
                decision_minute_offset=int(row_offset),
                selected_side=choice["side"],
                side_price=float(choice["side_price"]),
                side_fee=float(choice["side_fee"]),
                side_ev=float(choice["side_ev"]),
                probability=float(choice["probability"]),
                yes=int(choice["yes"]),
                contracts=contracts,
                pnl=pnl,
            )
        )

    pnls = [trade.pnl for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    expected_log_growth = None
    if len(equity_curve) > 1 and all(value > 0 for value in equity_curve):
        expected_log_growth = sum(
            math.log(equity_curve[index] / equity_curve[index - 1])
            for index in range(1, len(equity_curve))
        )
    return {
        "trade_count": len(trades),
        "executable_count": executable_count,
        "skipped_count": skipped_count,
        "net_pnl": equity - bankroll_dollars,
        "roi": (equity - bankroll_dollars) / bankroll_dollars,
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses else None,
        "max_drawdown": max_drawdown(equity_curve),
        "expected_log_growth": expected_log_growth,
        "fee_total": sum(trade.side_fee * trade.contracts for trade in trades),
        "ending_equity": equity,
        "trades": [trade.as_dict() for trade in trades],
    }


def summarize_policy_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: metrics.get(key)
        for key in (
            "trade_count",
            "executable_count",
            "skipped_count",
            "net_pnl",
            "expected_log_growth",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "fee_total",
        )
    }


def rows_for_candidate(
    rows: Iterable[Mapping[str, Any]],
    candidate: str,
    *,
    candidate_column: str = "candidate",
) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if str(row.get(candidate_column)) == candidate]
