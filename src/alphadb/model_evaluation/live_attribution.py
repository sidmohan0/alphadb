"""Live/paper attribution context for model evaluation reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alphadb.model_evaluation.io import file_sha256, load_json


@dataclass(frozen=True)
class LiveAttributionSummary:
    path: str | None
    sha256: str | None
    available: bool
    sample_size: int
    included_rows: int
    excluded_rows: int
    warnings: tuple[str, ...]
    pnl: Mapping[str, Any]
    breakdowns: Mapping[str, Any]
    promotion_status: str = "informational_only"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "kxbtc_live_attribution_context_v1",
            "path": self.path,
            "sha256": self.sha256,
            "available": self.available,
            "sample_size": self.sample_size,
            "included_rows": self.included_rows,
            "excluded_rows": self.excluded_rows,
            "warnings": list(self.warnings),
            "pnl": dict(self.pnl),
            "breakdowns": dict(self.breakdowns),
            "promotion_status": self.promotion_status,
            "non_promotion_notice": (
                "Live/paper attribution context is informational and cannot authorize "
                "model promotion or live-policy changes."
            ),
        }


def summarize_live_attribution(path: str | Path | None) -> LiveAttributionSummary:
    if path is None:
        return LiveAttributionSummary(
            path=None,
            sha256=None,
            available=False,
            sample_size=0,
            included_rows=0,
            excluded_rows=0,
            warnings=("missing_live_attribution_artifact",),
            pnl={},
            breakdowns={},
        )
    artifact_path = Path(path).expanduser().resolve()
    if not artifact_path.exists():
        return LiveAttributionSummary(
            path=str(artifact_path),
            sha256=None,
            available=False,
            sample_size=0,
            included_rows=0,
            excluded_rows=0,
            warnings=("missing_live_attribution_artifact",),
            pnl={},
            breakdowns={},
        )
    payload = load_json(artifact_path)
    return summary_from_payload(payload, path=str(artifact_path), sha256=file_sha256(artifact_path))


def summary_from_payload(
    payload: Mapping[str, Any],
    *,
    path: str | None = None,
    sha256: str | None = None,
) -> LiveAttributionSummary:
    warnings = tuple(str(item) for item in payload.get("warnings", ()) or ())
    headline = mapping(payload.get("headline"))
    data_quality = mapping(payload.get("data_quality"))
    filled = mapping(payload.get("filled_trade_breakdowns") or payload.get("filled_trades"))
    sample_size = int(
        numeric(
            data_quality.get("total_rows"),
            headline.get("total_markets"),
            headline.get("settled_reconciled_markets"),
            filled.get("settled_filled_trades"),
            default=0,
        )
    )
    included_rows = int(numeric(data_quality.get("pnl_included_rows"), default=sample_size))
    excluded_rows = int(numeric(data_quality.get("excluded_from_pnl"), default=0))
    generated_warnings = list(warnings)
    if sample_size < 100:
        generated_warnings.append("small_sample")
    if excluded_rows > 0:
        generated_warnings.append("excluded_coverage_present")
    return LiveAttributionSummary(
        path=path,
        sha256=sha256,
        available=True,
        sample_size=sample_size,
        included_rows=included_rows,
        excluded_rows=excluded_rows,
        warnings=tuple(dict.fromkeys(generated_warnings)),
        pnl={
            "actual_dollar_pnl": numeric(
                headline.get("actual_dollar_pnl"),
                payload.get("actual_dollar_pnl"),
                default=None,
            ),
            "one_contract_normalized_pnl": numeric(
                headline.get("one_contract_normalized_pnl"),
                payload.get("one_contract_normalized_pnl"),
                default=None,
            ),
        },
        breakdowns={
            "by_selected_edge": payload.get("by_selected_edge") or filled.get("by_selected_edge"),
            "by_entry_price": payload.get("by_entry_price") or filled.get("by_entry_price"),
            "by_selected_side": payload.get("by_selected_side") or filled.get("by_selected_side"),
            "by_decision_offset": payload.get("by_decision_offset") or filled.get("by_decision_offset"),
        },
    )


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def numeric(*values: Any, default: float | None = 0.0) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default
