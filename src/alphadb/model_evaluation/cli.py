"""CLI for generated KXBTC15M model evaluation reports."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from alphadb.config import settings_from_env
from alphadb.live_runtime import EXPENSIVE_YES_LIVE_STRATEGY, MARKET_CONTEXT_SOURCES
from alphadb.model_evaluation.artifacts import audit_model_artifacts
from alphadb.model_evaluation.edge import (
    build_edge_verdict_report,
    build_feature_pruning_report,
    build_focused_edge_walk_forward_report,
)
from alphadb.model_evaluation.fair_value_replay import (
    FairValueReplayConfig,
    build_fair_value_replay_report,
    build_fair_value_walk_forward_report,
    parse_min_edge_values,
)
from alphadb.model_evaluation.fair_value_live import (
    FairValueDecisionRowCollector,
    FairValueDecisionRowCollectorConfig,
    make_coinbase_client,
    make_kalshi_client,
)
from alphadb.model_evaluation.fair_value_live_job import (
    FairValueLiveTradingJob,
    FairValueLiveTradingJobConfig,
    parse_live_job_min_edge_values,
)
from alphadb.model_evaluation.fair_value_model import (
    ThresholdVolatilityFairValueConfig,
    build_threshold_volatility_fair_value_report,
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
from alphadb.research.execution_attribution import generate_execution_attribution


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

    execution = subparsers.add_parser(
        "execution-attribution",
        help="Generate execution/fill-speed attribution CSV and Markdown from live artifacts",
    )
    execution.add_argument("--input", required=True)
    execution.add_argument("--output-dir", required=True)
    execution.add_argument("--output", default=None)

    fair = subparsers.add_parser(
        "fair-value-replay",
        help="Replay fair-value strategy rows with default settlement/PnL reporting",
    )
    fair.add_argument("--rows", required=True)
    fair.add_argument("--probability-column", default="p_yes")
    fair.add_argument("--min-edge", type=float, default=0.0)
    fair.add_argument("--min-contract-price", type=float, default=0.0)
    fair.add_argument("--max-order-dollars", type=float, default=5.0)
    fair.add_argument("--max-loss-dollars", type=float, default=50.0)
    fair.add_argument("--taker-fee-multiplier", type=float, default=0.07)
    fair.add_argument("--output", default=None)

    fair_walk = subparsers.add_parser(
        "fair-value-walk-forward",
        help="Walk-forward fair-value replay with rolling selection/holdout windows",
    )
    fair_walk.add_argument("--rows", required=True)
    fair_walk.add_argument("--selection-market-count", type=int, required=True)
    fair_walk.add_argument("--holdout-market-count", type=int, required=True)
    fair_walk.add_argument("--step-market-count", type=int, default=None)
    fair_walk.add_argument("--min-edge-values", default="0.0")
    fair_walk.add_argument("--min-contract-price", type=float, default=0.0)
    fair_walk.add_argument("--probability-column", default="p_yes")
    fair_walk.add_argument("--max-order-dollars", type=float, default=5.0)
    fair_walk.add_argument("--max-loss-dollars", type=float, default=50.0)
    fair_walk.add_argument("--taker-fee-multiplier", type=float, default=0.07)
    fair_walk.add_argument("--output", default=None)

    fair_model = subparsers.add_parser(
        "fair-value-model",
        help="Score rows with the threshold/volatility fair-value model",
    )
    fair_model.add_argument("--rows", required=True)
    fair_model.add_argument("--price-column", default="external_close")
    fair_model.add_argument("--threshold-column", default="payout_threshold")
    fair_model.add_argument("--probability-column", default="p_yes")
    fair_model.add_argument("--output", default=None)

    fair_collect = subparsers.add_parser(
        "fair-value-collect-live-rows",
        help="Collect live-data fair-value decision rows without submitting orders",
    )
    fair_collect.add_argument("--source", choices=("fixture", "kalshi-public"), default="fixture")
    fair_collect.add_argument(
        "--coinbase-source",
        choices=("fixture", "coinbase-live"),
        default="fixture",
    )
    fair_collect.add_argument(
        "--market-context-source",
        choices=MARKET_CONTEXT_SOURCES,
        default="coinbase_primary",
    )
    fair_collect.add_argument("--max-markets", type=int, default=5)
    fair_collect.add_argument("--run-id", default=None)
    fair_collect.add_argument("--output", default=None)

    fair_live = subparsers.add_parser(
        "fair-value-live-trading-job",
        help="Run capped live-money fair-value canary with PnL/settlement artifacts",
    )
    fair_live.add_argument("--output-root", default="artifacts/fair-value-live")
    fair_live.add_argument("--source", choices=("fixture", "kalshi-public"), default="fixture")
    fair_live.add_argument(
        "--coinbase-source",
        choices=("fixture", "coinbase-live"),
        default="fixture",
    )
    fair_live.add_argument(
        "--market-context-source",
        choices=MARKET_CONTEXT_SOURCES,
        default="coinbase_primary",
    )
    fair_live.add_argument("--max-markets", type=int, default=20)
    fair_live.add_argument("--min-edge", type=float, default=0.0)
    fair_live.add_argument("--min-contract-price", type=float, default=0.25)
    fair_live.add_argument("--min-edge-values", default="0.0,0.05,0.10")
    fair_live.add_argument("--max-order-dollars", type=float, default=None)
    fair_live.add_argument("--max-ticker-exposure-dollars", type=float, default=None)
    fair_live.add_argument("--max-daily-loss-dollars", type=float, default=None)
    fair_live.add_argument("--selection-market-count", type=int, default=1)
    fair_live.add_argument("--holdout-market-count", type=int, default=1)
    fair_live.add_argument("--step-market-count", type=int, default=None)
    fair_live.add_argument("--s3-prefix", default=None)
    fair_live.add_argument("--submit-live-orders", action="store_true")
    fair_live.add_argument("--live-risk-state-stale-seconds", type=int, default=60)
    fair_live.add_argument("--quote-stale-seconds", type=int, default=15)
    fair_live.add_argument("--coinbase-feature-stale-seconds", type=int, default=90)
    fair_live.add_argument(
        "--runtime-config-source",
        choices=("auto", "postgres", "cli"),
        default="auto",
        help="Read dashboard-owned Postgres config, use CLI/env values, or choose by environment.",
    )
    fair_live.add_argument("--output", default=None)

    expensive_yes_live = subparsers.add_parser(
        "expensive-yes-live-trading-job",
        help="Run the guarded Expensive YES live-data probe",
    )
    expensive_yes_live.add_argument("--output-root", default="artifacts/expensive-yes-live")
    expensive_yes_live.add_argument(
        "--source", choices=("fixture", "kalshi-public"), default="fixture"
    )
    expensive_yes_live.add_argument(
        "--coinbase-source",
        choices=("fixture", "coinbase-live"),
        default="fixture",
    )
    expensive_yes_live.add_argument("--max-markets", type=int, default=10)
    expensive_yes_live.add_argument("--yes-ask-threshold", type=float, default=0.65)
    expensive_yes_live.add_argument("--max-order-dollars", type=float, default=1.0)
    expensive_yes_live.add_argument("--max-ticker-exposure-dollars", type=float, default=1.0)
    expensive_yes_live.add_argument("--max-daily-loss-dollars", type=float, default=10.0)
    expensive_yes_live.add_argument("--s3-prefix", default=None)
    expensive_yes_live.add_argument("--submit-live-orders", action="store_true")
    expensive_yes_live.add_argument("--live-risk-state-stale-seconds", type=int, default=60)
    expensive_yes_live.add_argument("--quote-stale-seconds", type=int, default=15)
    expensive_yes_live.add_argument(
        "--runtime-config-source",
        choices=("auto", "postgres", "cli"),
        default="auto",
        help="Read dashboard-owned Postgres config, use CLI values, or choose by environment.",
    )
    expensive_yes_live.add_argument("--output", default=None)

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
            load_json(Path(args.feature_pruning_report)) if args.feature_pruning_report else None
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
    elif args.command == "execution-attribution":
        payload = generate_execution_attribution(args.input, args.output_dir).as_dict()
    elif args.command == "fair-value-replay":
        payload = build_fair_value_replay_report(
            load_tabular_rows(Path(args.rows)),
            config=FairValueReplayConfig(
                probability_column=args.probability_column,
                min_edge=args.min_edge,
                min_contract_price=args.min_contract_price,
                max_order_dollars=args.max_order_dollars,
                max_loss_dollars=args.max_loss_dollars,
                taker_fee_multiplier=args.taker_fee_multiplier,
            ),
        )
    elif args.command == "fair-value-walk-forward":
        payload = build_fair_value_walk_forward_report(
            load_tabular_rows(Path(args.rows)),
            selection_market_count=args.selection_market_count,
            holdout_market_count=args.holdout_market_count,
            step_market_count=args.step_market_count,
            min_edge_values=parse_min_edge_values(args.min_edge_values),
            min_contract_price=args.min_contract_price,
            max_order_dollars=args.max_order_dollars,
            max_loss_dollars=args.max_loss_dollars,
            probability_column=args.probability_column,
            taker_fee_multiplier=args.taker_fee_multiplier,
        )
    elif args.command == "fair-value-model":
        payload = build_threshold_volatility_fair_value_report(
            load_tabular_rows(Path(args.rows)),
            config=ThresholdVolatilityFairValueConfig(
                price_column=args.price_column,
                threshold_column=args.threshold_column,
                probability_column=args.probability_column,
            ),
        )
    elif args.command == "fair-value-collect-live-rows":
        settings = settings_from_env()
        payload = (
            FairValueDecisionRowCollector(
                kalshi_client=make_kalshi_client(args.source, settings),
                coinbase_client=make_coinbase_client(args.coinbase_source),
                settings=settings,
                config=FairValueDecisionRowCollectorConfig(
                    max_markets=args.max_markets,
                    run_id=args.run_id,
                    source_mode=args.source,
                    coinbase_source_mode=args.coinbase_source,
                    market_context_source=args.market_context_source,
                ),
            )
            .collect()
            .as_dict()
        )
    elif args.command == "fair-value-live-trading-job":
        settings = settings_from_env()
        payload = FairValueLiveTradingJob(
            config=FairValueLiveTradingJobConfig(
                output_root=Path(args.output_root),
                source=args.source,
                coinbase_source=args.coinbase_source,
                market_context_source=args.market_context_source,
                max_markets=args.max_markets,
                min_edge=args.min_edge,
                min_contract_price=args.min_contract_price,
                min_edge_values=parse_live_job_min_edge_values(args.min_edge_values),
                max_order_dollars=args.max_order_dollars
                if args.max_order_dollars is not None
                else settings.live_stake_cap_dollars,
                max_ticker_exposure_dollars=args.max_ticker_exposure_dollars
                if args.max_ticker_exposure_dollars is not None
                else settings.max_ticker_exposure_dollars,
                max_daily_loss_dollars=args.max_daily_loss_dollars
                if args.max_daily_loss_dollars is not None
                else settings.max_daily_loss_dollars,
                selection_market_count=args.selection_market_count,
                holdout_market_count=args.holdout_market_count,
                step_market_count=args.step_market_count,
                s3_prefix=args.s3_prefix,
                submit_live_orders=args.submit_live_orders,
                runtime_config_source=args.runtime_config_source,
                live_risk_state_stale_seconds=args.live_risk_state_stale_seconds,
                quote_stale_seconds=args.quote_stale_seconds,
                coinbase_feature_stale_seconds=args.coinbase_feature_stale_seconds,
            )
        ).run()
    elif args.command == "expensive-yes-live-trading-job":
        payload = FairValueLiveTradingJob(
            config=FairValueLiveTradingJobConfig(
                output_root=Path(args.output_root),
                strategy=EXPENSIVE_YES_LIVE_STRATEGY,
                decision_policy="expensive_yes",
                source=args.source,
                coinbase_source=args.coinbase_source,
                max_markets=args.max_markets,
                min_edge=0.0,
                min_contract_price=args.yes_ask_threshold,
                min_edge_values=(0.0,),
                max_order_dollars=args.max_order_dollars,
                max_ticker_exposure_dollars=args.max_ticker_exposure_dollars,
                max_daily_loss_dollars=args.max_daily_loss_dollars,
                s3_prefix=args.s3_prefix,
                submit_live_orders=args.submit_live_orders,
                runtime_config_source=args.runtime_config_source,
                live_risk_state_stale_seconds=args.live_risk_state_stale_seconds,
                quote_stale_seconds=args.quote_stale_seconds,
                coinbase_feature_stale_seconds=0,
            )
        ).run()
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
