"""Helpers for live strategy process commands."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alphadb.config import Settings


LOG_DIR = Path("artifacts/strategy-manager")
LIVE_STRATEGIES = {
    "KXBTC15M single live cycle": "gated-live-cycle",
    "KXBTC15M live loop": "gated-live-loop",
}


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


def build_strategy_command(
    *,
    strategy_command: str,
    max_markets: int,
    poll_seconds: int,
    max_cycles: int,
    duration_minutes: float,
    daily_realized_pnl_dollars: float,
    stop_on_error: bool,
    extra_args: str,
) -> list[str]:
    command = ["alphadb-strategy", strategy_command, "--max-markets", str(max_markets)]
    if strategy_command == "gated-live-loop":
        command.extend(["--poll-seconds", str(poll_seconds)])
        if max_cycles > 0:
            command.extend(["--max-cycles", str(max_cycles)])
        if duration_minutes > 0:
            command.extend(["--duration-minutes", str(duration_minutes)])
        if not stop_on_error:
            command.append("--no-stop-on-error")
    else:
        command.extend(["--daily-realized-pnl-dollars", str(daily_realized_pnl_dollars)])
    if extra_args.strip():
        command.extend(shlex.split(extra_args))
    return command


def strategy_env(
    settings: Settings,
    *,
    live_stake_cap_dollars: float,
    max_daily_loss_dollars: float,
    min_ev_dollars: float,
    poll_seconds: int,
) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": settings.database_url,
            "ALPHADB_RUNTIME_MODE": "gated-live",
            "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
            "ALPHADB_LIVE_STAKE_CAP_DOLLARS": str(live_stake_cap_dollars),
            "ALPHADB_MAX_DAILY_LOSS_DOLLARS": str(max_daily_loss_dollars),
            "ALPHADB_MIN_EV_DOLLARS": str(min_ev_dollars),
            "ALPHADB_STRATEGY_POLL_SECONDS": str(poll_seconds),
        }
    )
    if settings.kalshi_api_key_id:
        env["KALSHI_API_KEY_ID"] = settings.kalshi_api_key_id
    if settings.kalshi_private_key_path:
        env["KALSHI_PRIVATE_KEY_PATH"] = settings.kalshi_private_key_path
    if settings.artifact_root:
        env["ALPHADB_ARTIFACT_ROOT"] = settings.artifact_root
    if settings.current_mvp_artifact_config:
        env["ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG"] = settings.current_mvp_artifact_config
    return env


def start_strategy(command: list[str], env: dict[str, str]) -> tuple[int, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"{stamp}-{'-'.join(command[1:3])}.log"
    log_file = log_path.open("ab", buffering=0)
    process = subprocess.Popen(
        command,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process.pid, log_path


def stop_strategy(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
