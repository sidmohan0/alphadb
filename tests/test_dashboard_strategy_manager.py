import pytest

from alphadb.config import settings_from_env

from alphadb.dashboard.strategy_manager import (
    LIVE_STRATEGIES,
    build_strategy_command,
    list_strategy_processes,
    parse_strategy_processes,
    strategy_env,
)


def test_strategy_manager_parses_existing_alphadb_strategy_processes() -> None:
    rows = parse_strategy_processes(
        """
          1     0 Ssl  /usr/local/bin/python /usr/local/bin/alphadb-dashboard --host 0.0.0.0
        389     1 Ssl  /usr/local/bin/python /usr/local/bin/alphadb-strategy gated-live-loop --max-markets 3
        """
    )

    assert len(rows) == 1
    assert rows[0].pid == 389
    assert "gated-live-loop" in rows[0].command


def test_strategy_manager_returns_no_processes_when_ps_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_ps(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("ps")

    monkeypatch.setattr("alphadb.dashboard.strategy_manager.subprocess.run", missing_ps)

    assert list_strategy_processes() == []


def test_strategy_manager_builds_live_loop_command_with_parameters() -> None:
    command = build_strategy_command(
        strategy_command="gated-live-loop",
        max_markets=3,
        poll_seconds=60,
        max_cycles=0,
        duration_minutes=0,
        daily_realized_pnl_dollars=0,
        stop_on_error=False,
        extra_args="--example value",
    )

    assert command == [
        "alphadb-strategy",
        "gated-live-loop",
        "--max-markets",
        "3",
        "--poll-seconds",
        "60",
        "--no-stop-on-error",
        "--example",
        "value",
    ]


def test_strategy_manager_defaults_to_single_cycle_before_live_loop() -> None:
    assert next(iter(LIVE_STRATEGIES.values())) == "gated-live-cycle"


def test_strategy_manager_live_env_sets_runtime_values() -> None:
    settings = settings_from_env(
        {
            "DATABASE_URL": "postgresql://example/db",
            "KALSHI_API_KEY_ID": "key",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
    )

    env = strategy_env(
        settings,
        live_stake_cap_dollars=10,
        max_daily_loss_dollars=30,
        min_ev_dollars=0.05,
        poll_seconds=15,
    )

    assert env["ALPHADB_RUNTIME_MODE"] == "gated-live"
    assert env["ALPHADB_ENABLE_LIVE_ORDERS"] == "1"
    assert env["ALPHADB_HUMAN_CUTOVER_APPROVED"] == "1"
    assert env["ALPHADB_LIVE_STAKE_CAP_DOLLARS"] == "10"
    assert env["ALPHADB_MAX_DAILY_LOSS_DOLLARS"] == "30"
    assert env["ALPHADB_MIN_EV_DOLLARS"] == "0.05"
    assert env["KALSHI_API_KEY_ID"] == "key"
