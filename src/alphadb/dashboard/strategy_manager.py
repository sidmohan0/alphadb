"""Streamlit controls for live strategy processes."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

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


def render_strategy_manager(settings: Settings) -> None:
    st.subheader("Strategy Manager")

    processes = list_strategy_processes()
    if processes:
        st.dataframe([process.as_dict() for process in processes], hide_index=True, use_container_width=True)
    else:
        st.dataframe([{"pid": "", "state": "not_running", "command": ""}], hide_index=True, use_container_width=True)

    selected_strategy = st.selectbox(
        "Strategy",
        options=list(LIVE_STRATEGIES),
        index=0,
        help="Choose which live KXBTC15M command to run. The loop keeps polling for new markets; the single cycle runs once and exits.",
    )
    strategy_command = LIVE_STRATEGIES[selected_strategy]

    left, middle, right = st.columns(3)
    max_markets = left.number_input(
        "Max markets",
        min_value=1,
        max_value=50,
        value=3,
        step=1,
        help="Maximum number of currently open markets to inspect in one cycle. Higher values scan more contracts before choosing what to trade.",
    )
    poll_seconds = middle.number_input(
        "Poll seconds",
        min_value=0,
        max_value=3600,
        value=int(settings.strategy_poll_seconds),
        step=5,
        help="Seconds to wait between loop cycles. A lower value checks the market more often.",
    )
    max_cycles = right.number_input(
        "Max cycles",
        min_value=0,
        max_value=100000,
        value=1,
        step=1,
        help="Stop after this many loop cycles. Use 0 to keep the loop running until you stop it.",
    )

    left, middle, right = st.columns(3)
    duration_minutes = left.number_input(
        "Duration minutes",
        min_value=0.0,
        max_value=10080.0,
        value=0.0,
        step=5.0,
        help="Stop the loop after this many minutes. Use 0 for no time limit.",
    )
    daily_realized_pnl_dollars = middle.number_input(
        "Daily realized P&L",
        value=0.0,
        step=1.0,
        help="Realized P&L to pass into a one-cycle run. Negative values mean losses already realized today.",
    )
    stop_on_error = right.checkbox(
        "Stop on cycle error",
        value=True,
        help="When enabled, the loop exits after an errored cycle. When disabled, it keeps running and records the error.",
    )

    left, middle, right = st.columns(3)
    live_stake_cap_dollars = left.number_input(
        "Per-trade dollars",
        min_value=0.0,
        max_value=100000.0,
        value=float(settings.live_stake_cap_dollars),
        step=1.0,
        help="Maximum dollars the strategy can allocate to a single order intent.",
    )
    max_daily_loss_dollars = middle.number_input(
        "Daily loss dollars",
        min_value=0.0,
        max_value=100000.0,
        value=float(settings.max_daily_loss_dollars),
        step=1.0,
        help="Daily loss value passed into the strategy runtime. The strategy uses it when sizing and deciding whether to keep submitting orders.",
    )
    min_ev_dollars = right.number_input(
        "Minimum EV dollars",
        value=float(settings.min_ev_dollars),
        step=0.01,
        format="%.4f",
        help="Minimum expected value required before a market becomes a trade signal.",
    )

    extra_args = st.text_input(
        "Extra CLI args",
        value="",
        help="Optional raw command-line arguments appended to the strategy command. Leave blank unless you need a parameter that is not shown above.",
    )

    command = build_strategy_command(
        strategy_command=strategy_command,
        max_markets=int(max_markets),
        poll_seconds=int(poll_seconds),
        max_cycles=int(max_cycles),
        duration_minutes=float(duration_minutes),
        daily_realized_pnl_dollars=float(daily_realized_pnl_dollars),
        stop_on_error=bool(stop_on_error),
        extra_args=extra_args,
    )
    st.code(" ".join(shlex.quote(part) for part in command), language="bash")

    start_col, stop_col, refresh_col = st.columns(3)
    if start_col.button(
        "Start",
        type="primary",
        help="Launch the selected strategy command with the parameters shown above.",
    ):
        pid, log_path = start_strategy(
            command,
            strategy_env(
                settings,
                live_stake_cap_dollars=float(live_stake_cap_dollars),
                max_daily_loss_dollars=float(max_daily_loss_dollars),
                min_ev_dollars=float(min_ev_dollars),
                poll_seconds=int(poll_seconds),
            ),
        )
        st.success(f"Started PID {pid}; logging to {log_path}")
        st.rerun()

    pids = [process.pid for process in processes]
    selected_pid = stop_col.selectbox(
        "PID to stop",
        options=pids,
        disabled=not pids,
        help="Choose the running alphadb-strategy process to stop.",
    )
    if stop_col.button(
        "Stop",
        disabled=not pids,
        help="Send SIGTERM to the selected strategy process.",
    ):
        stop_strategy(int(selected_pid))
        st.warning(f"Stopped PID {selected_pid}")
        st.rerun()

    if refresh_col.button(
        "Refresh",
        help="Reload process status and the latest dashboard tables.",
    ):
        st.rerun()
