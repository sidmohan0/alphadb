"""CLI for generated KXBTC15M model evaluation reports."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from alphadb.model_evaluation.artifacts import audit_model_artifacts
from alphadb.model_evaluation.edge import (
    build_edge_verdict_report,
    build_feature_pruning_report,
    build_focused_edge_walk_forward_report,
)
from alphadb.model_evaluation.io import load_json, load_tabular_rows, write_json
from alphadb.model_evaluation.live_attribution import summarize_live_attribution
from alphadb.model_evaluation.money_printer import (
    build_fillability_probe_report,
    build_nested_oos_edge_verdict_report,
    build_stale_quote_alpha_report,
    build_top_ev_sniper_policy_report,
)
from alphadb.model_evaluation.models import (
    build_feature_ablation_report,
    build_feature_set_comparison_report,
    compare_candidate_model_families,
)
from alphadb.model_evaluation.policy import build_holdout_policy_selection_report
from alphadb.model_evaluation.walk_forward import build_walk_forward_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-model-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="Audit KXBTC15M model artifacts")
    audit.add_argument("--artifact-root", required=True)
    audit.add_argument("--series", default="KXBTC15M")
    audit.add_argument("--output", default=None)

    holdout = subparsers.add_parser("holdout-policy", help="Build clean holdout policy report")
    holdout.add_argument("--predictions", required=True)
    holdout.add_argument("--output", default=None)

    walk = subparsers.add_parser("walk-forward", help="Build walk-forward report")
    walk.add_argument("--predictions", required=True)
    walk.add_argument("--selection-market-count", type=int, required=True)
    walk.add_argument("--holdout-market-count", type=int, required=True)
    walk.add_argument("--output", default=None)

    ablation = subparsers.add_parser("feature-ablation", help="Build feature ablation report")
    ablation.add_argument("--rows", required=True)
    ablation.add_argument("--feature-columns", required=True)
    ablation.add_argument("--candidate", default="logistic")
    ablation.add_argument("--external-signal-manifest", default=None)
    ablation.add_argument("--output", default=None)

    candidates = subparsers.add_parser("candidate-models", help="Compare candidate model families")
    candidates.add_argument("--rows", required=True)
    candidates.add_argument("--feature-columns", required=True)
    candidates.add_argument("--candidates", required=True)
    candidates.add_argument("--output", default=None)

    feature_set = subparsers.add_parser(
        "feature-set-comparison",
        help="Compare a baseline feature set against a named added feature group",
    )
    feature_set.add_argument("--rows", required=True)
    feature_set.add_argument("--feature-columns", required=True)
    feature_set.add_argument("--added-feature-group", default="coinbase_btc_market_structure")
    feature_set.add_argument("--candidate", default="fast_logistic")
    feature_set.add_argument("--output", default=None)

    pruning = subparsers.add_parser(
        "feature-pruning",
        help="Prune Coinbase/BTC market-structure features and diagnose policy mismatch",
    )
    pruning.add_argument("--rows", required=True)
    pruning.add_argument("--feature-columns", required=True)
    pruning.add_argument("--top-n", type=int, default=8)
    pruning.add_argument("--comparison-report", default=None)
    pruning.add_argument("--output", default=None)

    edge_walk = subparsers.add_parser(
        "edge-walk-forward",
        help="Run focused walk-forward Edge comparison for a slim Coinbase/BTC feature set",
    )
    edge_walk.add_argument("--rows", required=True)
    edge_walk.add_argument("--feature-columns", required=True)
    edge_walk.add_argument("--pruning-report", default=None)
    edge_walk.add_argument("--slim-feature-columns", default=None)
    edge_walk.add_argument("--selection-market-count", type=int, required=True)
    edge_walk.add_argument("--holdout-market-count", type=int, required=True)
    edge_walk.add_argument("--step-market-count", type=int, default=None)
    edge_walk.add_argument("--candidates", default="fast_logistic")
    edge_walk.add_argument("--output", default=None)

    edge_verdict = subparsers.add_parser(
        "edge-verdict",
        help="Build final Edge verdict report from focused evidence artifacts",
    )
    edge_verdict.add_argument("--edge-walk-forward-report", required=True)
    edge_verdict.add_argument("--feature-pruning-report", default=None)
    edge_verdict.add_argument("--raw-x-status", default="frozen_failed_branch")
    edge_verdict.add_argument("--output", default=None)

    nested = subparsers.add_parser(
        "nested-oos-edge",
        help="Run clean nested OOS Edge verdict with window-local feature selection",
    )
    nested.add_argument("--rows", required=True)
    nested.add_argument("--feature-columns", required=True)
    nested.add_argument("--top-n", type=int, default=8)
    nested.add_argument("--selection-market-count", type=int, required=True)
    nested.add_argument("--holdout-market-count", type=int, required=True)
    nested.add_argument("--step-market-count", type=int, default=None)
    nested.add_argument("--candidates", default="fast_logistic")
    nested.add_argument("--output", default=None)

    stale = subparsers.add_parser(
        "stale-quote",
        help="Detect Coinbase/BTC moves not reflected in KXBTC15M quote movement",
    )
    stale.add_argument("--rows", required=True)
    stale.add_argument("--windows-seconds", default="5,15,30,60")
    stale.add_argument("--min-btc-move-cents", type=float, default=0.5)
    stale.add_argument("--quote-reaction-ratio", type=float, default=0.5)
    stale.add_argument("--output", default=None)

    sniper = subparsers.add_parser(
        "top-ev-sniper",
        help="Build top-EV sniper policy report from nested OOS and stale-quote evidence",
    )
    sniper.add_argument("--rows", required=True)
    sniper.add_argument("--feature-columns", required=True)
    sniper.add_argument("--nested-oos-report", required=True)
    sniper.add_argument("--stale-quote-report", default=None)
    sniper.add_argument("--fee-multiplier", type=float, default=0.14)
    sniper.add_argument("--friction-spread-cents", type=float, default=1.0)
    sniper.add_argument("--min-ev", type=float, default=0.0)
    sniper.add_argument("--min-confidence", type=float, default=0.0)
    sniper.add_argument("--min-stale-quote-score", type=float, default=0.0)
    sniper.add_argument("--side", default="any")
    sniper.add_argument("--output", default=None)

    fillability = subparsers.add_parser(
        "fillability-probe",
        help="Build fillability probe report from opportunity/fill observations",
    )
    fillability.add_argument("--opportunities", required=True)
    fillability.add_argument("--ask-tolerance-cents", type=float, default=1.0)
    fillability.add_argument("--output", default=None)

    live = subparsers.add_parser("live-attribution", help="Summarize live/paper attribution")
    live.add_argument("--report", default=None)
    live.add_argument("--output", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "audit":
        payload = audit_model_artifacts(args.artifact_root, series=args.series).as_dict()
    elif args.command == "holdout-policy":
        payload = build_holdout_policy_selection_report(load_tabular_rows(Path(args.predictions)))
    elif args.command == "walk-forward":
        payload = build_walk_forward_report(
            load_tabular_rows(Path(args.predictions)),
            selection_market_count=args.selection_market_count,
            holdout_market_count=args.holdout_market_count,
        )
    elif args.command == "feature-ablation":
        payload = build_feature_ablation_report(
            load_tabular_rows(Path(args.rows)),
            feature_columns=parse_columns(args.feature_columns),
            candidate_name=args.candidate,
            external_signal_manifest=load_json(Path(args.external_signal_manifest))
            if args.external_signal_manifest
            else None,
        )
    elif args.command == "candidate-models":
        payload = compare_candidate_model_families(
            load_tabular_rows(Path(args.rows)),
            feature_columns=parse_columns(args.feature_columns),
            candidate_names=parse_columns(args.candidates),
        )
    elif args.command == "feature-set-comparison":
        payload = build_feature_set_comparison_report(
            load_tabular_rows(Path(args.rows)),
            feature_columns=parse_columns(args.feature_columns),
            added_feature_group=args.added_feature_group,
            candidate_name=args.candidate,
        )
    elif args.command == "feature-pruning":
        payload = build_feature_pruning_report(
            load_tabular_rows(Path(args.rows)),
            feature_columns=parse_columns(args.feature_columns),
            top_n=args.top_n,
            comparison_report=load_json(Path(args.comparison_report))
            if args.comparison_report
            else None,
        )
    elif args.command == "edge-walk-forward":
        pruning_report = load_json(Path(args.pruning_report)) if args.pruning_report else None
        payload = build_focused_edge_walk_forward_report(
            load_tabular_rows(Path(args.rows)),
            baseline_feature_columns=parse_columns(args.feature_columns),
            slim_feature_columns=edge_slim_feature_columns(args, pruning_report),
            selection_market_count=args.selection_market_count,
            holdout_market_count=args.holdout_market_count,
            step_market_count=args.step_market_count,
            candidate_names=parse_columns(args.candidates),
            feature_pruning_report=pruning_report,
        )
    elif args.command == "edge-verdict":
        edge_walk_report = load_json(Path(args.edge_walk_forward_report))
        pruning_report = (
            load_json(Path(args.feature_pruning_report))
            if args.feature_pruning_report
            else None
        )
        payload = build_edge_verdict_report(
            edge_walk_report.get("aggregate", edge_walk_report),
            feature_pruning_report=pruning_report,
            raw_x_status=args.raw_x_status,
        )
    elif args.command == "nested-oos-edge":
        payload = build_nested_oos_edge_verdict_report(
            load_tabular_rows(Path(args.rows)),
            feature_columns=parse_columns(args.feature_columns),
            top_n=args.top_n,
            selection_market_count=args.selection_market_count,
            holdout_market_count=args.holdout_market_count,
            step_market_count=args.step_market_count,
            candidate_names=parse_columns(args.candidates),
        )
    elif args.command == "stale-quote":
        payload = build_stale_quote_alpha_report(
            load_tabular_rows(Path(args.rows)),
            windows_seconds=parse_int_columns(args.windows_seconds),
            min_btc_move_cents=args.min_btc_move_cents,
            quote_reaction_ratio=args.quote_reaction_ratio,
        )
    elif args.command == "top-ev-sniper":
        payload = build_top_ev_sniper_policy_report(
            load_tabular_rows(Path(args.rows)),
            feature_columns=parse_columns(args.feature_columns),
            nested_oos_report=load_json(Path(args.nested_oos_report)),
            stale_quote_report=load_json(Path(args.stale_quote_report))
            if args.stale_quote_report
            else None,
            fee_multiplier=args.fee_multiplier,
            friction_spread_cents=args.friction_spread_cents,
            min_ev=args.min_ev,
            min_confidence=args.min_confidence,
            min_stale_quote_score=args.min_stale_quote_score,
            side=args.side,
        )
    elif args.command == "fillability-probe":
        payload = build_fillability_probe_report(
            load_tabular_rows(Path(args.opportunities)),
            ask_tolerance_cents=args.ask_tolerance_cents,
        )
    elif args.command == "live-attribution":
        payload = summarize_live_attribution(args.report).as_dict()
    else:
        raise AssertionError(f"unhandled command: {args.command}")
    if args.output:
        write_json(Path(args.output), payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def parse_columns(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_int_columns(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def edge_slim_feature_columns(args: argparse.Namespace, pruning_report: object | None) -> list[str]:
    if args.slim_feature_columns:
        return parse_columns(args.slim_feature_columns)
    if isinstance(pruning_report, dict):
        return [str(column) for column in pruning_report.get("slim_feature_columns", ())]
    raise ValueError("--slim-feature-columns or --pruning-report is required")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
