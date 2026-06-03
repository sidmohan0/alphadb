"""Candidate model-family comparison for KXBTC15M model evaluation."""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from alphadb.model_evaluation.features import (
    ablation_feature_sets,
    default_model_feature_columns,
    engineer_kxbtc_features,
    resolve_feature_groups,
)
from alphadb.model_evaluation.metrics import (
    calibration_buckets,
    optional_float,
    probability_metrics,
    simulate_policy,
    summarize_policy_metrics,
)
from alphadb.model_evaluation.policy import build_holdout_policy_selection_report, market_sort_keys


@dataclass(frozen=True)
class TrainedCandidate:
    name: str
    estimator: object
    feature_columns: tuple[str, ...]

    def predict_rows(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        matrix = feature_matrix(rows, self.feature_columns)
        probabilities = self.estimator.predict_proba(matrix)[:, 1]
        output: list[dict[str, Any]] = []
        for row, probability in zip(rows, probabilities, strict=True):
            payload = dict(row)
            payload["candidate"] = self.name
            payload["p_yes"] = float(probability)
            output.append(payload)
        return output


class AverageProbabilityEnsemble:
    def __init__(self, estimators: Sequence[object]):
        self.estimators = tuple(estimators)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        probabilities = [estimator.predict_proba(x)[:, 1] for estimator in self.estimators]
        mean = np.mean(np.vstack(probabilities), axis=0)
        return np.column_stack([1.0 - mean, mean])


def compare_candidate_model_families(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    candidate_names: Sequence[str],
    train_fraction: float = 0.5,
    selection_fraction: float = 0.25,
) -> dict[str, Any]:
    modeled = rows_with_numeric_features(engineer_kxbtc_features(rows), feature_columns)
    split = split_train_selection_holdout(
        modeled,
        train_fraction=train_fraction,
        selection_fraction=selection_fraction,
    )
    reports: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    trained_for_ensemble: list[TrainedCandidate] = []
    for candidate_name in candidate_names:
        if candidate_name == "simple_ensemble":
            continue
        candidate_report, trained = fit_and_report_candidate(
            candidate_name,
            train_rows=split["train"],
            evaluation_rows=split["selection"] + split["holdout"],
            feature_columns=feature_columns,
        )
        reports.append(candidate_report)
        if trained is not None:
            trained_for_ensemble.append(trained)
            predicted = trained.predict_rows(split["selection"] + split["holdout"])
            prediction_rows.extend(predicted)
            reports[-1] = candidate_prediction_report(candidate_name, predicted, split)
    if "simple_ensemble" in candidate_names:
        if len(trained_for_ensemble) < 2:
            reports.append(
                {
                    "candidate": "simple_ensemble",
                    "status": "skipped",
                    "skipped_reason": "requires at least two fitted base candidates",
                }
            )
        else:
            ensemble = TrainedCandidate(
                name="simple_ensemble",
                estimator=AverageProbabilityEnsemble(
                    [candidate.estimator for candidate in trained_for_ensemble]
                ),
                feature_columns=tuple(feature_columns),
            )
            predicted = ensemble.predict_rows(split["selection"] + split["holdout"])
            prediction_rows.extend(predicted)
            reports.append(candidate_prediction_report("simple_ensemble", predicted, split))

    holdout_report = None
    if prediction_rows:
        holdout_report = build_holdout_policy_selection_report(
            prediction_rows,
            selection_fraction=len(split["selection_markets"])
            / (len(split["selection_markets"]) + len(split["holdout_markets"])),
        )
    return {
        "schema_version": "kxbtc_candidate_model_family_comparison_v1",
        "split": {
            "train_market_count": len(split["train_markets"]),
            "selection_market_count": len(split["selection_markets"]),
            "holdout_market_count": len(split["holdout_markets"]),
        },
        "candidate_reports": reports,
        "policy_selection_report": holdout_report,
        "model_family_instability": summarize_model_family_instability(
            holdout_report,
            completed_candidates=[
                str(report.get("candidate"))
                for report in reports
                if report.get("status") == "complete" and report.get("candidate")
            ],
        ),
        "non_promotion_notice": (
            "Candidate model-family comparison informs research only and does not authorize "
            "model promotion or live trading."
        ),
    }


def build_feature_set_comparison_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    added_feature_group: str = "coinbase_btc_market_structure",
    candidate_name: str = "fast_logistic",
    train_fraction: float = 0.5,
    selection_fraction: float = 0.25,
) -> dict[str, Any]:
    engineered = engineer_kxbtc_features(rows)
    requested_columns = list(feature_columns)
    default_columns = default_model_feature_columns(requested_columns)
    excluded_raw_x = [column for column in requested_columns if column not in default_columns]
    engineered_columns = append_engineered_group_columns(default_columns, engineered, added_feature_group)
    groups = resolve_feature_groups(engineered_columns)
    added_columns = groups.get(added_feature_group, [])
    if not added_columns:
        raise ValueError(f"feature group {added_feature_group!r} produced no feature columns")
    added_set = set(added_columns)
    baseline_columns = [column for column in engineered_columns if column not in added_set]
    candidate_columns = [column for column in engineered_columns if column in set(baseline_columns) | added_set]
    modeled = rows_with_numeric_features(engineered, candidate_columns)
    split = split_train_selection_holdout(
        modeled,
        train_fraction=train_fraction,
        selection_fraction=selection_fraction,
    )
    evaluation_rows = split["selection"] + split["holdout"]
    arms = []
    for arm_name, columns in (
        ("baseline", baseline_columns),
        (f"baseline_plus_{added_feature_group}", candidate_columns),
    ):
        report, trained = fit_and_report_candidate(
            candidate_name,
            train_rows=split["train"],
            evaluation_rows=evaluation_rows,
            feature_columns=columns,
        )
        if trained is None:
            raise ValueError(f"{arm_name} failed to fit: {report.get('skipped_reason')}")
        predicted = rename_prediction_candidate(trained.predict_rows(evaluation_rows), arm_name)
        holdout_predicted = rows_for_markets(predicted, split["holdout_markets"])
        selection_predicted = rows_for_markets(predicted, split["selection_markets"])
        selection_policy = summarize_policy_metrics(simulate_policy(selection_predicted))
        holdout_policy = summarize_policy_metrics(simulate_policy(holdout_predicted))
        arms.append(
            {
                "name": arm_name,
                "candidate_model_family": candidate_name,
                "feature_count": len(columns),
                "feature_columns": list(columns),
                "selection_probability_metrics": probability_metrics(selection_predicted),
                "holdout_probability_metrics": probability_metrics(holdout_predicted),
                "policy": {
                    "candidate": arm_name,
                    "decision_minute_offset": None,
                    "min_ev": 0.0,
                    "min_confidence": 0.0,
                    "sizing": "fixed_dollars",
                },
                "selection_policy_metrics": selection_policy,
                "holdout_policy_metrics": holdout_policy,
                "stress_scenarios": build_direct_policy_stress_scenarios(holdout_predicted),
            }
        )
    baseline = arms[0]
    candidate = arms[1]
    return {
        "schema_version": "kxbtc_feature_set_comparison_report_v1",
        "mode": "baseline_vs_feature_group",
        "candidate_model_family": candidate_name,
        "raw_row_count": len(rows),
        "modeled_row_count_after_required_feature_dropna": len(modeled),
        "split_policy": "ticker ordered by market_open_time/decision_timestamp",
        "split": {
            "train_market_count": len(split["train_markets"]),
            "selection_market_count": len(split["selection_markets"]),
            "holdout_market_count": len(split["holdout_markets"]),
            "train_row_count": len(split["train"]),
            "selection_row_count": len(split["selection"]),
            "holdout_row_count": len(split["holdout"]),
        },
        "default_excluded_feature_columns": excluded_raw_x,
        "default_excluded_feature_groups": ["x_external_signal_state"] if excluded_raw_x else [],
        "added_feature_group": added_feature_group,
        "added_feature_columns": list(added_columns),
        "feature_groups": {key: list(value) for key, value in groups.items()},
        "baseline": baseline,
        f"baseline_plus_{added_feature_group}": candidate,
        "holdout_summary": prefixed_metric_delta(
            candidate["holdout_probability_metrics"],
            baseline["holdout_probability_metrics"],
            prefix=f"{added_feature_group}_minus_baseline",
            keys=("brier_score", "log_loss", "roc_auc", "average_precision", "accuracy_50"),
        ),
        "policy_summary": prefixed_metric_delta(
            candidate["holdout_policy_metrics"],
            baseline["holdout_policy_metrics"],
            prefix=f"{added_feature_group}_minus_baseline",
            keys=("net_pnl", "trade_count", "win_rate", "profit_factor", "max_drawdown", "fee_total"),
        ),
        "interpretation_note": (
            "Lower brier_score/log_loss/max_drawdown is better. Higher roc_auc, "
            "average_precision, net_pnl, win_rate, and profit_factor is better."
        ),
        "non_promotion_notice": (
            "Feature-set comparison informs research only and does not authorize model "
            "promotion, live trading, Current MVP changes, or target-platform cutover."
        ),
    }


def append_engineered_group_columns(
    feature_columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    group_name: str,
) -> list[str]:
    output = list(feature_columns)
    seen = set(output)
    if group_name != "coinbase_btc_market_structure":
        return output
    for row in rows:
        for column in row:
            if column.startswith("coinbase_btc_") and column not in seen:
                output.append(column)
                seen.add(column)
    return output


def rows_with_numeric_features(
    rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        yes = optional_float(row.get("yes"))
        if yes not in (0.0, 1.0):
            continue
        if all(optional_float(row.get(column)) is not None for column in feature_columns):
            output.append(dict(row))
    return output


def rename_prediction_candidate(
    rows: Sequence[Mapping[str, Any]],
    candidate_name: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["candidate"] = candidate_name
        output.append(payload)
    return output


def prefixed_metric_delta(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    prefix: str,
    keys: Sequence[str],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key in keys:
        candidate_value = optional_float(candidate.get(key))
        baseline_value = optional_float(baseline.get(key))
        output[f"{key}_{prefix}"] = (
            None if candidate_value is None or baseline_value is None else candidate_value - baseline_value
        )
    return output


def build_direct_policy_stress_scenarios(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    scenarios = [
        ("base_holdout", 0.07, 0.0),
        ("worse_spread_1_cents", 0.07, 1.0),
        ("fees_x_2", 0.14, 0.0),
        ("fees_x_2_worse_spread_1_cents", 0.14, 1.0),
    ]
    return [
        {
            "name": name,
            "split_role": "holdout_stress",
            "metrics": summarize_policy_metrics(
                simulate_policy(
                    rows,
                    taker_fee_multiplier=fee_multiplier,
                    extra_spread_cents=spread_cents,
                    recompute_fees=True,
                )
            ),
        }
        for name, fee_multiplier, spread_cents in scenarios
    ]


def build_feature_ablation_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    candidate_name: str = "logistic",
    external_signal_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    engineered = engineer_kxbtc_features(rows)
    configs = ablation_feature_sets(feature_columns)
    ablations: list[dict[str, Any]] = []
    for config in configs:
        candidate_columns = config["feature_columns"]
        try:
            report = compare_candidate_model_families(
                engineered,
                feature_columns=candidate_columns,
                candidate_names=[candidate_name],
            )
            status = "complete"
            skipped_reason = None
        except Exception as exc:
            report = {}
            status = "skipped"
            skipped_reason = f"{exc.__class__.__name__}: {exc}"
        ablations.append(
            {
                "name": config["name"],
                "mode": config["mode"],
                "group": config.get("group"),
                "feature_columns": list(candidate_columns),
                "status": status,
                "skipped_reason": skipped_reason,
                "report": report,
            }
        )
    payload = {
        "schema_version": "kxbtc_feature_group_ablation_report_v1",
        "baseline_feature_count": len(feature_columns),
        "ablations": ablations,
        "non_promotion_notice": (
            "Feature-group ablation informs research only and does not authorize "
            "model promotion or live trading."
        ),
    }
    if external_signal_manifest is not None:
        payload["external_signal_context"] = summarize_external_signal_manifest(
            external_signal_manifest
        )
    return payload


def summarize_external_signal_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    coverage = manifest.get("coverage")
    estimated_cost = manifest.get("estimated_cost")
    actual_cost = manifest.get("actual_cost")
    artifact_hashes = manifest.get("artifact_hashes")
    return {
        "dataset_id": manifest.get("dataset_id"),
        "source_identity": manifest.get("source_identity"),
        "source_mode": manifest.get("source_mode"),
        "query_catalog_version": manifest.get("query_catalog_version"),
        "tested_time_range": manifest.get("tested_time_range"),
        "coverage": dict(coverage) if isinstance(coverage, Mapping) else coverage,
        "estimated_cost": dict(estimated_cost)
        if isinstance(estimated_cost, Mapping)
        else estimated_cost,
        "actual_cost": dict(actual_cost) if isinstance(actual_cost, Mapping) else actual_cost,
        "artifact_hashes": dict(artifact_hashes)
        if isinstance(artifact_hashes, Mapping)
        else artifact_hashes,
        "suitability": manifest.get("suitability"),
        "exclusion_reasons": list(manifest.get("exclusion_reasons", ())),
        "non_promotion_notice": (
            "External signal context informs research only and does not authorize "
            "Model registry promotion, live trading, or Current MVP changes."
        ),
    }


def fit_and_report_candidate(
    candidate_name: str,
    *,
    train_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
) -> tuple[dict[str, Any], TrainedCandidate | None]:
    try:
        estimator = build_estimator(candidate_name)
    except Exception as exc:
        return (
            {
                "candidate": candidate_name,
                "status": "skipped",
                "skipped_reason": f"{exc.__class__.__name__}: {exc}",
            },
            None,
        )
    try:
        x_train = feature_matrix(train_rows, feature_columns)
        y_train = labels(train_rows)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            estimator.fit(x_train, y_train)
        trained = TrainedCandidate(
            name=candidate_name,
            estimator=estimator,
            feature_columns=tuple(feature_columns),
        )
        predicted = trained.predict_rows(evaluation_rows)
        return candidate_prediction_report(candidate_name, predicted, None), trained
    except Exception as exc:
        return (
            {
                "candidate": candidate_name,
                "status": "skipped",
                "skipped_reason": f"{exc.__class__.__name__}: {exc}",
            },
            None,
        )


def candidate_prediction_report(
    candidate_name: str,
    predicted: Sequence[Mapping[str, Any]],
    split: Mapping[str, Any] | None,
) -> dict[str, Any]:
    selection_markets = set(split.get("selection_markets", ())) if split else set()
    holdout_markets = set(split.get("holdout_markets", ())) if split else set()
    selection_rows = [
        row for row in predicted if not selection_markets or str(row.get("ticker")) in selection_markets
    ]
    holdout_rows = [
        row for row in predicted if holdout_markets and str(row.get("ticker")) in holdout_markets
    ]
    return {
        "candidate": candidate_name,
        "status": "complete",
        "selection_probability_metrics": probability_metrics(selection_rows),
        "selection_calibration": calibration_buckets(selection_rows),
        "holdout_probability_metrics": probability_metrics(holdout_rows or predicted),
        "holdout_calibration": calibration_buckets(holdout_rows or predicted),
    }


def summarize_model_family_instability(
    policy_selection_report: Mapping[str, Any] | None,
    *,
    completed_candidates: Sequence[str],
) -> dict[str, Any]:
    selected_candidate = None
    if isinstance(policy_selection_report, Mapping):
        selected_policy = policy_selection_report.get("selected_policy")
        if isinstance(selected_policy, Mapping):
            selected_candidate = selected_policy.get("candidate")
    unique_completed = sorted({candidate for candidate in completed_candidates if candidate})
    return {
        "completed_candidate_count": len(unique_completed),
        "completed_candidates": unique_completed,
        "selected_policy_candidate": selected_candidate,
        "status": "single_split_only",
        "note": (
            "Single split reports cannot prove model-family stability. Use walk-forward "
            "selected_candidate_counts for stability evidence across windows."
        ),
    }


def build_estimator(candidate_name: str) -> object:
    if candidate_name == "fast_logistic":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    SGDClassifier(
                        loss="log_loss",
                        max_iter=1000,
                        tol=1e-3,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        )
    if candidate_name == "logistic":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=300,
                        class_weight="balanced",
                        solver="lbfgs",
                        random_state=42,
                    ),
                ),
            ]
        )
    if candidate_name == "calibrated_logistic":
        return CalibratedClassifierCV(build_estimator("logistic"), method="sigmoid", cv=3)
    if candidate_name == "extra_trees":
        return ExtraTreesClassifier(
            n_estimators=120,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=42,
        )
    if candidate_name == "calibrated_extra_trees":
        return CalibratedClassifierCV(build_estimator("extra_trees"), method="sigmoid", cv=3)
    if candidate_name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            max_iter=120,
            learning_rate=0.05,
            l2_regularization=0.01,
            random_state=42,
        )
    if candidate_name == "lightgbm" or candidate_name == "calibrated_lightgbm":
        from lightgbm import LGBMClassifier  # type: ignore[import-not-found]

        estimator = LGBMClassifier(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.03,
            random_state=42,
            verbose=-1,
        )
        if candidate_name == "calibrated_lightgbm":
            return CalibratedClassifierCV(estimator, method="sigmoid", cv=3)
        return estimator
    if candidate_name == "xgboost":
        from xgboost import XGBClassifier  # type: ignore[import-not-found]

        return XGBClassifier(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            random_state=42,
        )
    if candidate_name == "catboost":
        from catboost import CatBoostClassifier  # type: ignore[import-not-found]

        return CatBoostClassifier(
            iterations=120,
            depth=3,
            learning_rate=0.03,
            loss_function="Logloss",
            verbose=False,
            random_seed=42,
        )
    raise ValueError(f"unknown candidate model family: {candidate_name}")


def split_train_selection_holdout(
    rows: Sequence[Mapping[str, Any]],
    *,
    train_fraction: float,
    selection_fraction: float,
) -> dict[str, Any]:
    if train_fraction <= 0 or selection_fraction <= 0 or train_fraction + selection_fraction >= 1:
        raise ValueError("train_fraction and selection_fraction must leave a positive holdout")
    sort_keys = market_sort_keys(rows)
    markets = sorted(sort_keys, key=lambda ticker: sort_keys[ticker])
    if len(markets) < 3:
        raise ValueError("at least three market tickers are required")
    train_end = max(1, int(len(markets) * train_fraction))
    selection_end = max(train_end + 1, int(len(markets) * (train_fraction + selection_fraction)))
    selection_end = min(selection_end, len(markets) - 1)
    train_markets = tuple(markets[:train_end])
    selection_markets = tuple(markets[train_end:selection_end])
    holdout_markets = tuple(markets[selection_end:])
    return {
        "train_markets": train_markets,
        "selection_markets": selection_markets,
        "holdout_markets": holdout_markets,
        "train": rows_for_markets(rows, train_markets),
        "selection": rows_for_markets(rows, selection_markets),
        "holdout": rows_for_markets(rows, holdout_markets),
    }


def rows_for_markets(rows: Sequence[Mapping[str, Any]], markets: Sequence[str]) -> list[dict[str, Any]]:
    market_set = set(markets)
    return [dict(row) for row in rows if str(row.get("ticker")) in market_set]


def feature_matrix(rows: Sequence[Mapping[str, Any]], feature_columns: Sequence[str]) -> np.ndarray:
    matrix: list[list[float]] = []
    for row in rows:
        values: list[float] = []
        for column in feature_columns:
            value = optional_float(row.get(column))
            if value is None:
                raise ValueError(f"missing numeric feature {column!r}")
            values.append(value)
        matrix.append(values)
    if not matrix:
        raise ValueError("no rows available for feature matrix")
    return np.asarray(matrix, dtype=float)


def labels(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    values = []
    for row in rows:
        value = optional_float(row.get("yes"))
        if value not in (0.0, 1.0):
            raise ValueError("training row missing binary yes label")
        values.append(int(value))
    if len(set(values)) < 2:
        raise ValueError("training labels need at least two classes")
    return np.asarray(values, dtype=int)
