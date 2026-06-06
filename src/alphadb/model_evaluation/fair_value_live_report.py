"""Read-only Fair-value Live 15m report generation."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

FAIR_VALUE_LIVE_REPORT_SCHEMA = "alphadb_fair_value_live_15m_report.v1"
DEFAULT_AWS_PROFILE = "alphadb"
DEFAULT_AWS_REGION = "us-east-2"
DEFAULT_BUCKET = "alphadb-artifacts-766780331843-us-east-2"
DEFAULT_S3_PREFIX = "fair-value-live"
FAIR_VALUE_RULE = "alphadb-fair-value-live"
STRUCTURAL_RULE = "alphadb-structural-live"
FAIR_VALUE_LOG_GROUP = "/ecs/alphadb-fair-value-live"
STRUCTURAL_LOG_GROUP = "/ecs/alphadb-structural-live"
FAIR_VALUE_CLUSTER = "alphadb-fair-value-live"
RETRYABLE_FAILURE_KINDS = {"dns_resolution_failed", "endpoint_connectivity_failed"}


class FairValueLiveReportError(RuntimeError):
    """Read-only report evidence failure with operator-facing classification."""

    def __init__(self, *, surface: str, kind: str, message: str):
        super().__init__(message)
        self.surface = surface
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class FairValueLiveReportConfig:
    aws_profile: str = DEFAULT_AWS_PROFILE
    aws_region: str = DEFAULT_AWS_REGION
    ec2_metadata_disabled: bool = True
    bucket: str = DEFAULT_BUCKET
    s3_prefix: str = DEFAULT_S3_PREFIX
    retry_delays_seconds: Sequence[float] = (60.0, 90.0, 120.0)
    sleeper: Callable[[float], None] = time.sleep


class FairValueLiveReportGenerator:
    def __init__(self, *, client: Any, config: FairValueLiveReportConfig | None = None):
        self.client = client
        self.config = config or FairValueLiveReportConfig()

    def generate(self, *, start: datetime, end: datetime) -> dict[str, Any]:
        start = ensure_utc(start)
        end = ensure_utc(end)
        surfaces: dict[str, dict[str, Any]] = {}
        values: dict[str, Any] = {}

        operations: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("sts", self.client.get_caller_identity),
            ("eventbridge_fair_value_rule", lambda: self.client.describe_rule(FAIR_VALUE_RULE)),
            ("eventbridge_structural_rule", lambda: self.client.describe_rule(STRUCTURAL_RULE)),
            ("eventbridge_fair_value_targets", lambda: self.client.list_targets_by_rule(FAIR_VALUE_RULE)),
            (
                "cloudwatch_fair_value_logs",
                lambda: self.client.filter_log_events(
                    log_group_name=FAIR_VALUE_LOG_GROUP,
                    start=start - timedelta(minutes=2),
                    end=end + timedelta(minutes=2),
                ),
            ),
            (
                "cloudwatch_fair_value_errors",
                lambda: self.client.filter_log_events(
                    log_group_name=FAIR_VALUE_LOG_GROUP,
                    start=start - timedelta(minutes=2),
                    end=end + timedelta(minutes=2),
                    filter_pattern="ERROR OR Exception OR Traceback OR failed",
                ),
            ),
            (
                "cloudwatch_structural_logs",
                lambda: self.client.filter_log_events(
                    log_group_name=STRUCTURAL_LOG_GROUP,
                    start=start,
                    end=end,
                ),
            ),
            (
                "ecs_fair_value_tasks",
                lambda: self.client.list_stopped_tasks(
                    cluster=FAIR_VALUE_CLUSTER,
                    start=start,
                    end=end,
                ),
            ),
            (
                "s3_artifacts",
                lambda: self.client.list_s3_run_prefixes(
                    bucket=self.config.bucket,
                    prefix=self.config.s3_prefix,
                ),
            ),
        )

        attempts_by_surface = {name: 0 for name, _operation in operations}
        pending = [name for name, _operation in operations]
        operations_by_name = dict(operations)
        delays = list(self.config.retry_delays_seconds)
        for attempt_index in range(len(delays) + 1):
            for name in tuple(pending):
                attempts_by_surface[name] += 1
                try:
                    value = operations_by_name[name]()
                except FairValueLiveReportError as exc:
                    surfaces[name] = failed_surface(exc, attempts=attempts_by_surface[name])
                except Exception as exc:  # pragma: no cover - exercised by boto3 client integration
                    surfaces[name] = failed_surface(
                        classify_exception(name, exc),
                        attempts=attempts_by_surface[name],
                    )
                else:
                    surfaces[name] = {
                        "status": "ok",
                        "attempts": attempts_by_surface[name],
                        "value": value,
                    }
                    values[name] = value
                    pending.remove(name)
                    continue
                if surfaces[name].get("failure_kind") not in RETRYABLE_FAILURE_KINDS:
                    pending.remove(name)
            retryable_pending = [
                name
                for name in pending
                if surfaces.get(name, {}).get("failure_kind") in RETRYABLE_FAILURE_KINDS
            ]
            if not retryable_pending or attempt_index >= len(delays):
                break
            delay = delays[attempt_index]
            if delay > 0:
                self.config.sleeper(delay)

        runs = self._load_interval_runs(values.get("s3_artifacts", []), start=start, end=end)
        summary = build_summary(values=values, runs=runs)
        successful_surfaces = [name for name, surface in surfaces.items() if surface["status"] == "ok"]
        failed_surfaces = [name for name, surface in surfaces.items() if surface["status"] == "failed"]

        status = "complete"
        if not successful_surfaces:
            status = "blocked"
        elif failed_surfaces:
            status = "partial"

        report: dict[str, Any] = {
            "schema_version": FAIR_VALUE_LIVE_REPORT_SCHEMA,
            "interval": {"start": start.isoformat(), "end": end.isoformat()},
            "status": status,
            "aws_config": {
                "profile": getattr(self.client, "aws_profile", self.config.aws_profile),
                "region": getattr(self.client, "aws_region", self.config.aws_region),
                "ec2_metadata_disabled": bool(
                    getattr(
                        self.client,
                        "ec2_metadata_disabled",
                        self.config.ec2_metadata_disabled,
                    )
                ),
            },
            "surfaces": strip_surface_values(surfaces),
            "summary": summary,
            "runs": runs,
        }
        if status == "blocked":
            report["block_reason"] = dominant_failure_kind(surfaces)
        if status == "partial":
            report["missing_surfaces"] = failed_surfaces
        return report

    def _load_interval_runs(
        self,
        run_prefixes: Sequence[str],
        *,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for run_prefix in run_prefixes:
            run_id = run_id_from_prefix(run_prefix)
            if not run_id:
                continue
            timestamp = timestamp_from_run_id(run_id)
            if timestamp is not None and not (start <= timestamp < end):
                continue
            base_key = f"{self.config.s3_prefix.rstrip('/')}/{run_id}"
            artifacts: dict[str, Any] = {}
            for artifact_name in (
                "manifest",
                "decision_rows",
                "live_order_attempts",
                "live_reconciliation_report",
            ):
                key = f"{base_key}/{artifact_name}.json"
                try:
                    artifacts[artifact_name] = self.client.load_s3_json(
                        bucket=self.config.bucket,
                        key=key,
                    )
                except Exception as exc:
                    artifacts[f"{artifact_name}_error"] = classify_exception(
                        f"s3:{key}",
                        exc,
                    ).kind
            manifest = as_mapping(artifacts.get("manifest"))
            generated_at = parse_datetime(manifest.get("generated_at")) or timestamp
            if generated_at is not None and not (start <= generated_at < end):
                continue
            runs.append(summarize_run(run_id=run_id, artifacts=artifacts))
        return runs


class Boto3FairValueLiveEvidenceClient:
    """Small read-only AWS evidence adapter for the report generator."""

    def __init__(
        self,
        *,
        aws_profile: str = DEFAULT_AWS_PROFILE,
        aws_region: str = DEFAULT_AWS_REGION,
        ec2_metadata_disabled: bool = True,
    ):
        self.aws_profile = aws_profile
        self.aws_region = aws_region
        self.ec2_metadata_disabled = ec2_metadata_disabled
        if ec2_metadata_disabled:
            os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
        import boto3  # type: ignore[import-not-found]

        self._session = boto3.Session(profile_name=aws_profile, region_name=aws_region)

    def get_caller_identity(self) -> dict[str, Any]:
        return self._call("sts", "sts", lambda: self._session.client("sts").get_caller_identity())

    def describe_rule(self, name: str) -> dict[str, Any]:
        return self._call(
            f"eventbridge:{name}",
            "eventbridge",
            lambda: self._session.client("events").describe_rule(Name=name),
        )

    def list_targets_by_rule(self, name: str) -> list[dict[str, Any]]:
        def call() -> list[dict[str, Any]]:
            client = self._session.client("events")
            response = client.list_targets_by_rule(Rule=name)
            return list(response.get("Targets", []))

        return self._call(f"eventbridge-targets:{name}", "eventbridge", call)

    def filter_log_events(
        self,
        *,
        log_group_name: str,
        start: datetime,
        end: datetime,
        filter_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        def call() -> list[dict[str, Any]]:
            client = self._session.client("logs")
            kwargs: dict[str, Any] = {
                "logGroupName": log_group_name,
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
            }
            if filter_pattern:
                kwargs["filterPattern"] = filter_pattern
            events: list[dict[str, Any]] = []
            while True:
                response = client.filter_log_events(**kwargs)
                events.extend(response.get("events", []))
                token = response.get("nextToken")
                if not token:
                    return events
                kwargs["nextToken"] = token

        return self._call(f"cloudwatch:{log_group_name}", "cloudwatch", call)

    def list_stopped_tasks(self, *, cluster: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        def call() -> list[dict[str, Any]]:
            client = self._session.client("ecs")
            response = client.list_tasks(cluster=cluster, desiredStatus="STOPPED", maxResults=100)
            arns = response.get("taskArns", [])
            if not arns:
                return []
            described = client.describe_tasks(cluster=cluster, tasks=arns)
            output = []
            for task in described.get("tasks", []):
                started = parse_datetime(task.get("startedAt"))
                stopped = parse_datetime(task.get("stoppedAt"))
                if stopped and start <= stopped < end:
                    output.append(task)
                elif started and start <= started < end:
                    output.append(task)
            return output

        return self._call(f"ecs:{cluster}", "ecs", call)

    def list_s3_run_prefixes(self, *, bucket: str, prefix: str) -> list[str]:
        def call() -> list[str]:
            client = self._session.client("s3")
            paginator = client.get_paginator("list_objects_v2")
            prefixes: list[str] = []
            for page in paginator.paginate(
                Bucket=bucket,
                Prefix=f"{prefix.rstrip('/')}/fv_live_",
                Delimiter="/",
            ):
                prefixes.extend(item["Prefix"] for item in page.get("CommonPrefixes", []))
            return prefixes

        return self._call(f"s3:{bucket}/{prefix}", "s3", call)

    def load_s3_json(self, *, bucket: str, key: str) -> dict[str, Any]:
        def call() -> dict[str, Any]:
            response = self._session.client("s3").get_object(Bucket=bucket, Key=key)
            payload = json.loads(response["Body"].read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError(f"S3 artifact must be a JSON object: s3://{bucket}/{key}")
            return dict(payload)

        return self._call(f"s3:{bucket}/{key}", "s3", call)

    def _call(self, surface: str, service: str, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except Exception as exc:
            raise classify_exception(surface, exc, service=service) from exc


def build_summary(*, values: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fair_rule = as_mapping(values.get("eventbridge_fair_value_rule"))
    structural_rule = as_mapping(values.get("eventbridge_structural_rule"))
    targets = as_sequence(values.get("eventbridge_fair_value_targets"))
    tasks = as_sequence(values.get("ecs_fair_value_tasks"))
    fair_errors = as_sequence(values.get("cloudwatch_fair_value_errors"))
    structural_logs = as_sequence(values.get("cloudwatch_structural_logs"))
    order_counter: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    filled_contracts = 0
    order_ids: list[str] = []
    for run in runs:
        orders = as_mapping(run.get("orders"))
        order_counter.update(
            {
                "submitted": int(orders.get("submitted") or 0),
                "skipped": int(orders.get("skipped") or 0),
                "rejected": int(orders.get("rejected") or 0),
                "errors": int(orders.get("errors") or 0),
            }
        )
        filled_contracts += int(orders.get("filled_contracts") or 0)
        order_ids.extend(str(order_id) for order_id in orders.get("order_ids", []) if order_id)
        skip_reasons.update(as_mapping(orders.get("skip_reasons")))
    return {
        "schedule_state": fair_rule.get("State"),
        "legacy_structural_schedule_state": structural_rule.get("State"),
        "target_task_definition": first_task_definition(targets),
        "run_count": len(runs),
        "ecs_success_count": sum(1 for task in tasks if task_exit_code(task) == 0),
        "ecs_failure_count": sum(1 for task in tasks if task_exit_code(task) not in (None, 0)),
        "fair_value_error_log_count": len(fair_errors),
        "legacy_structural_live_activity": bool(structural_logs),
        "config": latest_value(runs, "runtime_config"),
        "runtime_guard": latest_value(runs, "runtime_guard"),
        "executable_quote": latest_value(runs, "executable_quote"),
        "one_cycle": latest_value(runs, "one_cycle"),
        "hot_path_scope": latest_value(runs, "hot_path_scope"),
        "live_risk_admission_state": latest_value(runs, "live_risk_admission_state"),
        "orders": {
            "submitted": order_counter["submitted"],
            "skipped": order_counter["skipped"],
            "rejected": order_counter["rejected"],
            "errors": order_counter["errors"],
            "filled_contracts": filled_contracts,
            **({"order_ids": order_ids} if order_ids else {}),
            **({"skip_reasons": dict(skip_reasons)} if skip_reasons else {}),
        },
        "reconciliation": latest_value(runs, "reconciliation"),
    }


def summarize_run(*, run_id: str, artifacts: Mapping[str, Any]) -> dict[str, Any]:
    manifest = as_mapping(artifacts.get("manifest"))
    attempts_payload = as_mapping(artifacts.get("live_order_attempts"))
    reconciliation = as_mapping(artifacts.get("live_reconciliation_report"))
    attempts = as_sequence(attempts_payload.get("attempts"))
    orders = summarize_attempts(attempts=attempts, reconciliation=reconciliation)
    return {
        "run_id": run_id,
        "generated_at": manifest.get("generated_at"),
        "runtime_config": manifest.get("runtime_config"),
        "runtime_guard": as_mapping(manifest.get("runtime_controls")).get("runtime_guard"),
        "executable_quote": manifest.get("executable_quote"),
        "one_cycle": manifest.get("one_cycle"),
        "hot_path_scope": manifest.get("hot_path_scope"),
        "live_risk_admission_state": manifest.get("live_risk_admission_state"),
        "selected_decision": manifest.get("selected_decision"),
        "orders": orders,
        "reconciliation": summarize_reconciliation(reconciliation),
    }


def summarize_attempts(
    *,
    attempts: Sequence[Any],
    reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    counter: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    order_ids: list[str] = []
    for attempt in attempts:
        row = as_mapping(attempt)
        status = str(row.get("status") or "unknown")
        if status == "error":
            counter["errors"] += 1
        else:
            counter[status] += 1
        if status == "skipped":
            skip_reasons[str(row.get("reason") or "unknown")] += 1
        if row.get("order_id"):
            order_ids.append(str(row["order_id"]))
    pnl = as_mapping(reconciliation.get("pnl"))
    return {
        "submitted": counter["submitted"],
        "skipped": counter["skipped"],
        "rejected": counter["rejected"],
        "errors": counter["errors"],
        "filled_contracts": int(pnl.get("filled_contracts") or 0),
        **({"order_ids": order_ids} if order_ids else {}),
        **({"skip_reasons": dict(skip_reasons)} if skip_reasons else {}),
    }


def summarize_reconciliation(reconciliation: Mapping[str, Any]) -> dict[str, Any]:
    settlement = as_mapping(reconciliation.get("settlement"))
    pnl = as_mapping(reconciliation.get("pnl"))
    rows = as_sequence(reconciliation.get("rows"))
    return {
        "settlement_status": settlement.get("status"),
        "settled_rows": settlement.get("settled_rows"),
        "unsettled_rows": settlement.get("unsettled_rows"),
        "filled_contracts": int(pnl.get("filled_contracts") or 0),
        "gross_cost_dollars": float(pnl.get("gross_cost_dollars") or 0.0),
        "fees_dollars": float(pnl.get("fees_dollars") or 0.0),
        "payout_dollars": float(pnl.get("payout_dollars") or 0.0),
        "net_pnl_dollars": float(pnl.get("net_pnl_dollars") or 0.0),
        "unsettled_exposure_dollars": float(pnl.get("unsettled_exposure_dollars") or 0.0),
        "rows": [dict(as_mapping(row)) for row in rows],
    }


def strip_surface_values(surfaces: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for name, surface in surfaces.items():
        output[name] = {key: value for key, value in surface.items() if key != "value"}
    return output


def failed_surface(error: FairValueLiveReportError, *, attempts: int) -> dict[str, Any]:
    return {
        "status": "failed",
        "attempts": attempts,
        "failure_kind": error.kind,
        "message": error.message,
    }


def dominant_failure_kind(surfaces: Mapping[str, Mapping[str, Any]]) -> str:
    kinds = [
        str(surface.get("failure_kind"))
        for surface in surfaces.values()
        if surface.get("status") == "failed" and surface.get("failure_kind")
    ]
    if not kinds:
        return "unknown"
    return Counter(kinds).most_common(1)[0][0]


def classify_exception(
    surface: str,
    exc: Exception,
    *,
    service: str | None = None,
) -> FairValueLiveReportError:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if (
        "could not resolve" in lowered
        or "name or service not known" in lowered
        or "temporary failure in name resolution" in lowered
        or "nodename nor servname" in lowered
        or "dns" in lowered
    ):
        kind = "dns_resolution_failed"
    elif (
        "expired" in lowered
        or "sso" in lowered
        or "unauthorized" in lowered
        or "accessdenied" in lowered
        or "invalid token" in lowered
    ):
        kind = "auth_failed"
    elif (
        "endpointconnection" in lowered
        or "could not connect to the endpoint url" in lowered
        or "connect timeout" in lowered
        or "connection refused" in lowered
    ):
        kind = "endpoint_connectivity_failed"
    else:
        kind = "surface_read_failed"
    return FairValueLiveReportError(
        surface=service or surface,
        kind=kind,
        message=str(exc),
    )


def first_task_definition(targets: Sequence[Any]) -> str | None:
    for target in targets:
        ecs = as_mapping(as_mapping(target).get("EcsParameters"))
        task_definition = ecs.get("TaskDefinitionArn")
        if task_definition:
            return str(task_definition)
    return None


def task_exit_code(task: Any) -> int | None:
    containers = as_sequence(as_mapping(task).get("containers"))
    for container in containers:
        value = as_mapping(container).get("exitCode")
        if value is not None:
            return int(value)
    return None


def latest_value(runs: Sequence[Mapping[str, Any]], key: str) -> Any:
    for run in reversed(runs):
        value = run.get(key)
        if value not in (None, {}, []):
            return value
    return None


def run_id_from_prefix(prefix: str) -> str | None:
    match = re.search(r"(fv_live_\d{8}T\d{6}Z)", prefix)
    return match.group(1) if match else None


def timestamp_from_run_id(run_id: str) -> datetime | None:
    match = re.fullmatch(r"fv_live_(\d{8}T\d{6})Z", run_id)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    try:
        return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def as_sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-fair-value-live-report")
    parser.add_argument("--start", required=True, help="Interval start timestamp")
    parser.add_argument("--end", required=True, help="Interval end timestamp")
    parser.add_argument("--aws-profile", default=DEFAULT_AWS_PROFILE)
    parser.add_argument("--aws-region", default=DEFAULT_AWS_REGION)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--s3-prefix", default=DEFAULT_S3_PREFIX)
    parser.add_argument("--retry-delays-seconds", default="60,90,120")
    parser.add_argument("--output", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = FairValueLiveReportConfig(
        aws_profile=args.aws_profile,
        aws_region=args.aws_region,
        bucket=args.bucket,
        s3_prefix=args.s3_prefix,
        retry_delays_seconds=parse_retry_delays(args.retry_delays_seconds),
    )
    client = Boto3FairValueLiveEvidenceClient(
        aws_profile=config.aws_profile,
        aws_region=config.aws_region,
        ec2_metadata_disabled=config.ec2_metadata_disabled,
    )
    report = FairValueLiveReportGenerator(client=client, config=config).generate(
        start=parse_required_datetime(args.start),
        end=parse_required_datetime(args.end),
    )
    payload = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
    else:
        print(payload)
    return 0


def parse_retry_delays(value: str) -> tuple[float, ...]:
    if not value.strip():
        return ()
    return tuple(float(part.strip()) for part in value.split(",") if part.strip())


def parse_required_datetime(value: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"invalid timestamp: {value}")
    return parsed


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
