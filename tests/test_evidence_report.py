from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.evidence import EvidenceReportBuilder
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.strategy.state import StrategyRunRepository, fresh_outcome
from alphadb.state.repository import OperationalStateRepository


def evidence_repository_or_skip() -> OperationalStateRepository:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository


def run_with_outcome(repository: OperationalStateRepository, *, status: str = "handled", scanned: int = 1):
    started = datetime(2026, 5, 31, 21, 0, tzinfo=UTC)
    run = StrategyRunRepository(repository.database_url).start_run(
        market_series="KXBTC15M",
        runtime_mode="paper",
        started_at=started,
    )
    tracer = repository.create_tracer_run(kxbtc15m_spec(), now=started)
    StrategyRunRepository(repository.database_url).record_outcome(
        fresh_outcome(
            run_id=run.run_id,
            market_ticker=tracer.market_ticker,
            decision_timestamp=started + timedelta(hours=1),
            status=status,
            reason=None if status == "handled" else "test_error",
            latency_checkpoints={"ingestion_ms": 1.0, "model_inference_ms": 2.0},
        )
    )
    StrategyRunRepository(repository.database_url).finish_run(
        run_id=run.run_id,
        status="completed",
        metadata_patch={"latest_counts": {"scanned": scanned, "waiting": 0}},
    )
    return run.run_id, tracer.market_ticker, started


def test_evidence_report_passes_for_complete_one_hour_run() -> None:
    repository = evidence_repository_or_skip()
    run_id, _market_ticker, started = run_with_outcome(repository)

    report = EvidenceReportBuilder(repository.database_url).build(
        run_id=run_id,
        observed_end=started + timedelta(hours=1),
    )

    assert report.pass_criteria_met is True
    assert report.duration_seconds == 3600
    assert report.counts["scanned"] == 1
    assert report.latency_checkpoints["model_inference_ms_avg"] == 2.0


def test_evidence_report_fails_for_errors_missing_outcomes_and_mismatches() -> None:
    repository = evidence_repository_or_skip()
    error_run, _error_market, started = run_with_outcome(repository, status="error")
    missing_run, _missing_market, _started = run_with_outcome(repository, scanned=2)
    mismatch_run, mismatch_market, _started = run_with_outcome(repository)

    with repository.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into shadow_comparisons (
                    comparison_id,
                    market_ticker,
                    decision_timestamp,
                    status,
                    mismatch_count,
                    intentional_difference_count,
                    alpha_payload,
                    current_mvp_payload,
                    comparisons
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"shadow_evidence_mismatch_{uuid4().hex}",
                    mismatch_market,
                    started + timedelta(hours=1),
                    "mismatch",
                    1,
                    0,
                    Jsonb({"market_ticker": mismatch_market}),
                    Jsonb({"market_ticker": mismatch_market}),
                    Jsonb([]),
                ),
            )
        connection.commit()

    error_report = EvidenceReportBuilder(repository.database_url).build(
        run_id=error_run,
        observed_end=started + timedelta(hours=1),
    )
    missing_report = EvidenceReportBuilder(repository.database_url).build(
        run_id=missing_run,
        observed_end=started + timedelta(hours=1),
    )
    mismatch_report = EvidenceReportBuilder(repository.database_url).build(
        run_id=mismatch_run,
        observed_end=started + timedelta(hours=1),
    )

    assert "unhandled_errors_present" in error_report.failure_reasons
    assert "missing_handled_outcomes" in missing_report.failure_reasons
    assert "unexplained_shadow_mismatches" in mismatch_report.failure_reasons
