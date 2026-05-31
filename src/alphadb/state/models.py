"""Operational state records used by the first Postgres tracer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperationalCounts:
    runs: int
    market_instances: int
    decisions: int
    risk_decisions: int
    order_intents: int

    def as_dict(self) -> dict[str, int]:
        return {
            "runs": self.runs,
            "market_instances": self.market_instances,
            "decisions": self.decisions,
            "risk_decisions": self.risk_decisions,
            "order_intents": self.order_intents,
        }


@dataclass(frozen=True)
class TracerRunRecord:
    run_id: str
    market_ticker: str
    decision_id: str
    risk_decision_id: str
    order_intent_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "market_ticker": self.market_ticker,
            "decision_id": self.decision_id,
            "risk_decision_id": self.risk_decision_id,
            "order_intent_id": self.order_intent_id,
        }
