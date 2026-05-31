"""Deterministic event-driven replay report."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from alphadb.config import settings_from_env
from alphadb.decision_engine.engine import (
    DecisionEngine,
    DecisionRepository,
    build_decision_input,
)
from alphadb.events.log import RawEventLog, canonical_payload_hash
from alphadb.features.ledger import FeatureRowBuilder
from alphadb.markets.registry import default_market_registry
from alphadb.model_registry.registry import ModelRegistryRepository
from alphadb.paper.ioc import PaperExecutionResult, PaperIocExecutor, PaperLiquidity
from alphadb.risk.gate import (
    RiskDecisionRepository,
    RiskGate,
    RiskPolicy,
    RiskState,
)
from alphadb.state.repository import OperationalStateRepository


@dataclass(frozen=True)
class ReplayReport:
    run_id: str
    market_ticker: str
    model_id: str
    model_artifact_uri: str
    model_artifact_sha256: str
    raw_event_ids: tuple[str, ...]
    raw_event_payload_hashes: tuple[str, ...]
    feature_row_id: str
    feature_row_hash: str
    source_event_ids: tuple[str, ...]
    source_lag_ms: int
    decision_id: str
    selected_side: str | None
    selected_ev_dollars: float | None
    skip_reason: str | None
    risk_decision_id: str
    risk_status: str
    risk_reason: str | None
    paper_order_id: str | None
    paper_status: str | None
    filled_quantity: int
    realized_pnl_dollars: float
    unrealized_pnl_dollars: float
    report_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "market_ticker": self.market_ticker,
            "model_id": self.model_id,
            "model_artifact_uri": self.model_artifact_uri,
            "model_artifact_sha256": self.model_artifact_sha256,
            "raw_event_ids": list(self.raw_event_ids),
            "raw_event_payload_hashes": list(self.raw_event_payload_hashes),
            "feature_row_id": self.feature_row_id,
            "feature_row_hash": self.feature_row_hash,
            "source_event_ids": list(self.source_event_ids),
            "source_lag_ms": self.source_lag_ms,
            "decision_id": self.decision_id,
            "selected_side": self.selected_side,
            "selected_ev_dollars": self.selected_ev_dollars,
            "skip_reason": self.skip_reason,
            "risk_decision_id": self.risk_decision_id,
            "risk_status": self.risk_status,
            "risk_reason": self.risk_reason,
            "paper_order_id": self.paper_order_id,
            "paper_status": self.paper_status,
            "filled_quantity": self.filled_quantity,
            "realized_pnl_dollars": self.realized_pnl_dollars,
            "unrealized_pnl_dollars": self.unrealized_pnl_dollars,
            "report_hash": self.report_hash,
        }


class ReplayReporter:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def run(
        self,
        *,
        run_id: str,
        market_ticker: str,
        model_id: str,
        decision_timestamp: datetime,
        probability_yes: float,
        realized_pnl_dollars: float,
        liquidity_price_dollars: float | None = None,
        liquidity_quantity: int = 1,
        mark_price_dollars: float | None = None,
        series: str = "KXBTC15M",
    ) -> ReplayReport:
        OperationalStateRepository(self.database_url).apply_migrations()
        spec = default_market_registry().get(series)
        raw_events = list(
            RawEventLog(self.database_url).replay_events(
                run_id=run_id,
                market_ticker=market_ticker,
            )
        )
        model = ModelRegistryRepository(self.database_url).get(model_id)
        feature_row = FeatureRowBuilder(self.database_url).build(
            run_id=run_id,
            market_ticker=market_ticker,
            model_id=model_id,
            decision_timestamp=decision_timestamp,
            expected_feature_version=model.feature_version,
            expected_dataset_id=model.dataset_id,
        )
        decision = DecisionRepository(self.database_url).persist(
            DecisionEngine().evaluate(
                build_decision_input(
                    spec=spec,
                    feature_row=feature_row,
                    probability_yes=probability_yes,
                )
            )
        )
        risk = RiskDecisionRepository(self.database_url).persist(
            RiskGate().evaluate(
                decision=decision,
                policy=RiskPolicy.from_spec(spec),
                state=RiskState(
                    trading_day=decision_timestamp.date(),
                    realized_pnl_dollars=realized_pnl_dollars,
                ),
            )
        )
        paper: PaperExecutionResult | None = None
        if risk.order_intent is not None:
            paper = PaperIocExecutor(self.database_url).execute(
                order_intent_id=risk.order_intent.order_intent_id,
                liquidity=PaperLiquidity(
                    side=risk.order_intent.side,
                    available_price_dollars=(
                        liquidity_price_dollars
                        if liquidity_price_dollars is not None
                        else risk.order_intent.price_dollars
                    ),
                    available_quantity=liquidity_quantity,
                    mark_price_dollars=mark_price_dollars,
                ),
                executed_at=decision_timestamp,
            )

        report_payload = {
            "run_id": run_id,
            "market_ticker": market_ticker,
            "model_id": model_id,
            "raw_event_ids": [str(event["raw_event_id"]) for event in raw_events],
            "feature_row_hash": feature_row.row_hash,
            "decision_id": decision.decision_id,
            "risk_decision_id": risk.risk_decision_id,
            "paper_order_id": None if paper is None else paper.paper_order_id,
        }
        report_hash = canonical_payload_hash(report_payload)
        return ReplayReport(
            run_id=run_id,
            market_ticker=market_ticker,
            model_id=model_id,
            model_artifact_uri=model.artifact_uri,
            model_artifact_sha256=model.artifact_sha256,
            raw_event_ids=tuple(str(event["raw_event_id"]) for event in raw_events),
            raw_event_payload_hashes=tuple(str(event["payload_hash"]) for event in raw_events),
            feature_row_id=feature_row.feature_row_id,
            feature_row_hash=feature_row.row_hash,
            source_event_ids=tuple(feature_row.source_event_ids),
            source_lag_ms=feature_row.source_lag_ms,
            decision_id=decision.decision_id,
            selected_side=decision.selected_side,
            selected_ev_dollars=decision.selected_ev_dollars,
            skip_reason=decision.skip_reason,
            risk_decision_id=risk.risk_decision_id,
            risk_status=risk.status,
            risk_reason=risk.reason,
            paper_order_id=None if paper is None else paper.paper_order_id,
            paper_status=None if paper is None else paper.status,
            filled_quantity=0 if paper is None else paper.filled_quantity,
            realized_pnl_dollars=0 if paper is None else paper.realized_pnl_dollars,
            unrealized_pnl_dollars=0 if paper is None else paper.unrealized_pnl_dollars,
            report_hash=report_hash,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-replay")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="Build one replay report")
    report_parser.add_argument("--run-id", required=True)
    report_parser.add_argument("--market-ticker", required=True)
    report_parser.add_argument("--model-id", required=True)
    report_parser.add_argument("--decision-timestamp", required=True)
    report_parser.add_argument("--probability-yes", type=float, required=True)
    report_parser.add_argument("--realized-pnl-dollars", type=float, default=0.0)
    report_parser.add_argument("--liquidity-price-dollars", type=float, default=None)
    report_parser.add_argument("--liquidity-quantity", type=int, default=1)
    report_parser.add_argument("--mark-price-dollars", type=float, default=None)
    report_parser.add_argument("--series", default="KXBTC15M")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()

    if args.command == "report":
        report = ReplayReporter(settings.database_url).run(
            run_id=args.run_id,
            market_ticker=args.market_ticker,
            model_id=args.model_id,
            decision_timestamp=datetime.fromisoformat(
                args.decision_timestamp.replace("Z", "+00:00")
            ).astimezone(UTC),
            probability_yes=args.probability_yes,
            realized_pnl_dollars=args.realized_pnl_dollars,
            liquidity_price_dollars=args.liquidity_price_dollars,
            liquidity_quantity=args.liquidity_quantity,
            mark_price_dollars=args.mark_price_dollars,
            series=args.series,
        )
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
