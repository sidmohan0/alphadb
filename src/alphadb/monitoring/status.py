"""Read-only machine status command for AlphaDB operations."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from alphadb.config import Settings, settings_from_env
from alphadb.health import HealthReport, collect_health
from alphadb.strategy.state import StrategyRunRepository


DEFAULT_EXPECTED_COMMAND = "alphadb-strategy gated-live-loop"
DEFAULT_EXPECTED_RUN_STATUS = "running"
DEFAULT_EXPECTED_PROCESS_COUNT = 1


@dataclass(frozen=True)
class StrategyProcess:
    pid: int
    ppid: int
    state: str
    command: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "ppid": self.ppid,
            "state": self.state,
            "command": self.command,
        }


ProcessLister = Callable[[], list[StrategyProcess]]
HealthCollector = Callable[[Settings], HealthReport]
StrategyRepositoryFactory = Callable[[str], StrategyRunRepository]


def parse_strategy_processes(ps_output: str) -> list[StrategyProcess]:
    processes: list[StrategyProcess] = []
    for line in ps_output.splitlines():
        parts = line.strip().split(maxsplit=3)
        if len(parts) != 4:
            continue
        pid, ppid, state, command = parts
        if "alphadb-strategy" not in command:
            continue
        try:
            processes.append(
                StrategyProcess(
                    pid=int(pid),
                    ppid=int(ppid),
                    state=state,
                    command=command,
                )
            )
        except ValueError:
            continue
    return processes


def list_strategy_processes() -> list[StrategyProcess]:
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,stat=,args="],
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    return parse_strategy_processes(result.stdout)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]
    return value


def health_report_dict(report: HealthReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "service": report.service,
        "environment": report.environment,
        "generated_at_utc": report.generated_at_utc.isoformat(),
        "components": report.as_rows(),
    }


def _safe_latest_run(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    safe_metadata_keys = {
        "runner",
        "guard",
        "latest_counts",
        "loop_status",
        "cycles_completed",
        "model_artifact_sha256",
        "feature_schema_sha256",
        "live_stake_cap_dollars",
        "max_daily_loss_dollars",
        "min_ev_dollars",
    }
    safe_metadata = {}
    if isinstance(metadata, Mapping):
        safe_metadata = {
            key: value for key, value in dict(metadata).items() if key in safe_metadata_keys
        }
    return _json_safe(
        {
            "run_id": row.get("run_id"),
            "mode": row.get("mode"),
            "market_series": row.get("market_series"),
            "status": row.get("status"),
            "started_at": row.get("started_at"),
            "created_at": row.get("created_at"),
            "metadata": safe_metadata,
        }
    )


def _safe_outcome(row: Mapping[str, Any]) -> dict[str, Any]:
    safe_keys = {
        "run_id",
        "runtime_mode",
        "market_ticker",
        "decision_timestamp",
        "status",
        "reason",
        "selected_side",
        "skip_reason",
        "risk_status",
        "risk_reason",
        "paper_status",
        "live_submission_status",
        "live_order_created_at",
    }
    return _json_safe({key: row.get(key) for key in safe_keys if key in row})


def collect_process_status(
    *,
    process_lister: ProcessLister = list_strategy_processes,
    expected_command: str = DEFAULT_EXPECTED_COMMAND,
    expected_count: int = DEFAULT_EXPECTED_PROCESS_COUNT,
) -> dict[str, Any]:
    processes = process_lister()
    matches = [process for process in processes if expected_command in process.command]
    ok = len(matches) == expected_count
    return {
        "ok": ok,
        "expected_command": expected_command,
        "expected_count": expected_count,
        "count": len(matches),
        "matches": [process.as_dict() for process in matches],
        "detail": (
            "expected process count matched"
            if ok
            else f"expected {expected_count} matching process(es), found {len(matches)}"
        ),
    }


def collect_strategy_status(
    settings: Settings,
    *,
    repository_factory: StrategyRepositoryFactory = StrategyRunRepository,
    expected_run_status: str = DEFAULT_EXPECTED_RUN_STATUS,
) -> dict[str, Any]:
    try:
        repository = repository_factory(settings.database_url)
        latest_run = repository.latest_run()
        if latest_run is None:
            return {
                "ok": False,
                "expected_run_status": expected_run_status,
                "latest_run_status": None,
                "latest_run": None,
                "counts": {},
                "latest_outcomes": [],
                "detail": "no strategy run found",
            }
        run_id = str(latest_run["run_id"])
        counts = repository.counts(run_id=run_id)
        latest_outcomes = repository.latest_outcomes(run_id=run_id, limit=10)
    except Exception as exc:
        return {
            "ok": False,
            "expected_run_status": expected_run_status,
            "latest_run_status": None,
            "latest_run": None,
            "counts": {},
            "latest_outcomes": [],
            "detail": f"strategy status unavailable: {exc}",
        }

    latest_run_status = str(latest_run["status"])
    ok = latest_run_status == expected_run_status
    return {
        "ok": ok,
        "expected_run_status": expected_run_status,
        "latest_run_status": latest_run_status,
        "latest_run": _safe_latest_run(latest_run),
        "counts": _json_safe(counts),
        "latest_outcomes": [_safe_outcome(row) for row in latest_outcomes],
        "detail": (
            "latest run status matched"
            if ok
            else f"expected latest run status {expected_run_status!r}, found {latest_run_status!r}"
        ),
    }


def collect_monitor_status(
    settings: Settings | None = None,
    *,
    health_collector: HealthCollector = collect_health,
    process_lister: ProcessLister = list_strategy_processes,
    repository_factory: StrategyRepositoryFactory = StrategyRunRepository,
    expected_command: str = DEFAULT_EXPECTED_COMMAND,
    expected_run_status: str = DEFAULT_EXPECTED_RUN_STATUS,
    expected_process_count: int = DEFAULT_EXPECTED_PROCESS_COUNT,
) -> dict[str, Any]:
    resolved_settings = settings or settings_from_env()
    try:
        health = health_report_dict(health_collector(resolved_settings))
    except Exception as exc:
        health = {
            "ok": False,
            "service": "alphadb",
            "environment": resolved_settings.environment,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "components": [],
            "detail": f"health status unavailable: {exc}",
        }
    process = collect_process_status(
        process_lister=process_lister,
        expected_command=expected_command,
        expected_count=expected_process_count,
    )
    strategy = collect_strategy_status(
        resolved_settings,
        repository_factory=repository_factory,
        expected_run_status=expected_run_status,
    )
    ok = bool(health["ok"] and process["ok"] and strategy["ok"])
    return {
        "ok": ok,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "checks": {
            "health": bool(health["ok"]),
            "strategy_process": bool(process["ok"]),
            "strategy_latest_run": bool(strategy["ok"]),
        },
        "health": health,
        "strategy_process": process,
        "strategy": strategy,
    }


def render_text(status: Mapping[str, Any]) -> str:
    lines = [
        f"ok: {str(status.get('ok')).lower()}",
        f"generated_at_utc: {status.get('generated_at_utc')}",
    ]
    process = status.get("strategy_process", {})
    if isinstance(process, Mapping):
        lines.append(
            "strategy_process: "
            f"{process.get('count')}/{process.get('expected_count')} "
            f"{process.get('expected_command')} - {process.get('detail')}"
        )
    strategy = status.get("strategy", {})
    if isinstance(strategy, Mapping):
        lines.append(
            "strategy_latest_run: "
            f"{strategy.get('latest_run_status')} "
            f"(expected {strategy.get('expected_run_status')}) - {strategy.get('detail')}"
        )
    checks = status.get("checks", {})
    if isinstance(checks, Mapping):
        for name, passed in checks.items():
            lines.append(f"{name}: {'ok' if passed else 'error'}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="Show read-only machine status")
    status.add_argument("--json", action="store_true", help="Emit JSON output")
    status.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    status.add_argument("--expected-command", default=DEFAULT_EXPECTED_COMMAND)
    status.add_argument("--expected-run-status", default=DEFAULT_EXPECTED_RUN_STATUS)
    status.add_argument("--expected-process-count", type=int, default=DEFAULT_EXPECTED_PROCESS_COUNT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        status = collect_monitor_status(
            expected_command=args.expected_command,
            expected_run_status=args.expected_run_status,
            expected_process_count=args.expected_process_count,
        )
        if args.json or args.pretty:
            print(json.dumps(status, indent=2 if args.pretty else None, sort_keys=True))
        else:
            print(render_text(status))
        return 0 if status["ok"] else 1
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
