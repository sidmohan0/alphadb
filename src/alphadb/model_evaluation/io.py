"""Dependency-light artifact readers for model evaluation reports."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


TABULAR_SUFFIXES = {".csv", ".json", ".jsonl", ".parquet"}


class ModelEvaluationDataError(ValueError):
    """Raised when model evaluation input data cannot be interpreted safely."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ModelEvaluationDataError(f"JSON artifact must contain an object: {path}")
    return payload


def load_tabular_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise ModelEvaluationDataError(
                    f"JSONL row {line_number} must contain an object: {path}"
                )
            rows.append(dict(payload))
        return rows
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping):
            if isinstance(payload.get("rows"), list):
                payload = payload["rows"]
            elif isinstance(payload.get("predictions"), list):
                payload = payload["predictions"]
        if not isinstance(payload, list):
            raise ModelEvaluationDataError(f"JSON tabular artifact must contain a list: {path}")
        if any(not isinstance(row, Mapping) for row in payload):
            raise ModelEvaluationDataError(f"JSON tabular rows must be objects: {path}")
        return [dict(row) for row in payload]
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix == ".parquet":
        try:
            import pandas as pd  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional environment
            raise ModelEvaluationDataError(
                "Parquet model evaluation inputs require pandas/pyarrow to be installed"
            ) from exc
        return [dict(row) for row in pd.read_parquet(path).to_dict(orient="records")]
    raise ModelEvaluationDataError(f"unsupported tabular artifact suffix: {path.suffix}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def unique_in_order(values: Sequence[Any]) -> list[Any]:
    seen: set[Any] = set()
    output: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
