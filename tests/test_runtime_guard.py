from alphadb.config import settings_from_env
from alphadb.runtime import RuntimeMode, evaluate_runtime_guard, runtime_status_rows


def test_runtime_guard_defaults_to_fixture_fail_closed() -> None:
    settings = settings_from_env({})

    decision = evaluate_runtime_guard(settings)

    assert decision.runtime_mode == RuntimeMode.FIXTURE
    assert decision.can_submit_live_orders is False
    assert decision.paper_orders_allowed is False
    assert decision.denial_reason == "runtime_mode_fixture_disables_live_orders"


def test_runtime_guard_denies_fixture_shadow_and_paper_live_orders() -> None:
    for mode in ("fixture", "shadow", "paper"):
        decision = evaluate_runtime_guard(settings_from_env({"ALPHADB_RUNTIME_MODE": mode}))

        assert decision.can_submit_live_orders is False
        assert decision.live_enabled is False

    paper = evaluate_runtime_guard(settings_from_env({"ALPHADB_RUNTIME_MODE": "paper"}))
    assert paper.paper_orders_allowed is True
    assert paper.denial_reason == "paper_mode_disables_live_orders"


def test_runtime_guard_gated_live_requires_explicit_config_credentials_and_human_gate() -> None:
    missing_enable = evaluate_runtime_guard(settings_from_env({"ALPHADB_RUNTIME_MODE": "gated-live"}))
    missing_credentials = evaluate_runtime_guard(
        settings_from_env(
            {
                "ALPHADB_RUNTIME_MODE": "gated-live",
                "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            }
        )
    )
    missing_human_gate = evaluate_runtime_guard(
        settings_from_env(
            {
                "ALPHADB_RUNTIME_MODE": "gated-live",
                "ALPHADB_ENABLE_LIVE_ORDERS": "1",
                "KALSHI_API_KEY_ID": "key",
                "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
            }
        )
    )
    allowed = evaluate_runtime_guard(
        settings_from_env(
            {
                "ALPHADB_RUNTIME_MODE": "gated-live",
                "ALPHADB_ENABLE_LIVE_ORDERS": "1",
                "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
                "KALSHI_API_KEY_ID": "key",
                "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
            }
        )
    )

    assert missing_enable.denial_reason == "live_orders_not_explicitly_enabled"
    assert missing_credentials.denial_reason == "missing_kalshi_credentials"
    assert missing_human_gate.denial_reason == "missing_human_cutover_approval"
    assert allowed.can_submit_live_orders is True
    assert allowed.denial_reason is None


def test_runtime_status_rows_expose_dashboard_guard_state() -> None:
    rows = runtime_status_rows(settings_from_env({"ALPHADB_RUNTIME_MODE": "paper"}))

    assert {"metric": "runtime_mode", "value": "paper"} in rows
    assert {"metric": "guard_denial_reason", "value": "paper_mode_disables_live_orders"} in rows
