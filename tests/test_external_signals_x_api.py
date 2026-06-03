from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from alphadb.external_signals.cli import env_with_dotenv
from alphadb.external_signals.x_api import (
    FixtureXCountsClient,
    HttpXCountsClient,
    XBudgetError,
    XCostBudget,
    XCredentialError,
    XNoLookaheadError,
    XQueryCatalog,
    XQueryCategory,
    XResponseError,
    collect_x_counts_dataset,
    estimate_x_counts_cost,
    generate_minimal_x_features,
    materialize_x_signal_features,
    validate_x_signal_feature_rows,
)
from alphadb.model_evaluation.features import resolve_feature_groups
from alphadb.model_evaluation.models import build_feature_ablation_report


def small_catalog() -> XQueryCatalog:
    return XQueryCatalog(
        version="x_api.query_catalog.test.v1",
        categories=(
            XQueryCategory(
                name="btc_general",
                description="Bitcoin fixture volume",
                query="bitcoin lang:en -is:retweet",
            ),
            XQueryCategory(
                name="macro_rates",
                description="Macro fixture volume",
                query="FOMC OR CPI OR rates lang:en -is:retweet",
            ),
        ),
    )


def approved_budget() -> XCostBudget:
    return XCostBudget(daily_cap_usd=1.0)


def test_x_query_catalog_cost_estimate_fails_closed_on_budget() -> None:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 2, tzinfo=UTC)
    report = estimate_x_counts_cost(
        market="KXBTC15M",
        start=start,
        end=end,
        budget=XCostBudget(daily_cap_usd=0.03),
        catalog=small_catalog(),
    )

    payload = report.as_dict()

    assert payload["budget_status"] == "approved"
    assert payload["estimated_request_count"] == 2
    assert payload["estimated_cost_usd"] == pytest.approx(0.02)
    assert payload["budget"] == {"daily_cap_usd": 0.03}
    assert all("query" not in line for line in payload["lines"])

    rejected = estimate_x_counts_cost(
        market="KXBTC15M",
        start=start,
        end=end,
        budget=XCostBudget(daily_cap_usd=0.01),
        catalog=small_catalog(),
    )
    assert rejected.as_dict()["budget_status"] == "rejected"
    with pytest.raises(XBudgetError):
        rejected.assert_approved()


def test_fixture_x_counts_dataset_writes_private_artifacts_and_manifest(tmp_path: Path) -> None:
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 5, 1, 0, 30, tzinfo=UTC)
    payloads = {
        "btc_general": [
            {
                "data": [
                    {
                        "start": "2026-05-01T00:00:00Z",
                        "end": "2026-05-01T00:01:00Z",
                        "tweet_count": 3,
                    }
                ],
                "meta": {"total_tweet_count": 3},
            }
        ],
        "macro_rates": [
            {
                "data": [
                    {
                        "start": "2026-05-01T00:10:00Z",
                        "end": "2026-05-01T00:11:00Z",
                        "tweet_count": 5,
                    }
                ],
                "meta": {"total_tweet_count": 5},
            }
        ],
    }

    result = collect_x_counts_dataset(
        market="KXBTC15M",
        start=start,
        end=end,
        output_root=tmp_path / "research",
        budget=approved_budget(),
        client=FixtureXCountsClient(payloads),
        catalog=small_catalog(),
        source_mode="fixture",
        retrieved_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    manifest = result.manifest

    assert result.counts_path.exists()
    assert result.manifest_path.exists()
    assert "research" in result.counts_path.parts
    assert manifest["source_identity"] == "x_api"
    assert manifest["source_mode"] == "fixture"
    assert manifest["coverage"]["row_count"] == 2
    assert manifest["actual_cost"]["cost_usd"] == 0.0
    assert manifest["artifact_hashes"]["counts_jsonl_sha256"]
    assert "query" not in manifest["query_categories"][0]
    assert "token" not in str(manifest).lower()


def test_fixture_dataset_records_partial_failures_without_complete_suitability(
    tmp_path: Path,
) -> None:
    result = collect_x_counts_dataset(
        market="KXBTC15M",
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, 1, tzinfo=UTC),
        output_root=tmp_path / "artifacts",
        budget=approved_budget(),
        client=FixtureXCountsClient(
            {
                "btc_general": [
                    {
                        "data": [
                            {
                                "start": "2026-05-01T00:00:00Z",
                                "end": "2026-05-01T00:01:00Z",
                                "tweet_count": "not-a-count",
                            }
                        ]
                    }
                ],
                "macro_rates": [{"data": []}],
            }
        ),
        catalog=small_catalog(),
        source_mode="fixture",
        allow_partial=True,
    )

    assert result.manifest["suitability"] == "inconclusive"
    assert result.manifest["exclusion_reasons"]

    with pytest.raises(XResponseError):
        collect_x_counts_dataset(
            market="KXBTC15M",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2026, 5, 1, 1, tzinfo=UTC),
            output_root=tmp_path / "artifacts",
            budget=approved_budget(),
            client=FixtureXCountsClient({"btc_general": [{"data": "bad"}]}),
            catalog=XQueryCatalog(
                version="x_api.query_catalog.test.v1",
                categories=(
                    XQueryCategory(
                        name="btc_general",
                        description="Bitcoin fixture volume",
                        query="bitcoin lang:en",
                    ),
                ),
            ),
            source_mode="fixture",
        )


def test_materialize_x_signal_features_preserves_no_lookahead_and_retrieval_provenance() -> None:
    manifest = {
        "dataset_id": "x_counts_test",
        "query_catalog_version": "x_api.query_catalog.test.v1",
    }
    counts = [
        {
            "category": "btc_general",
            "start": "2026-05-01T00:00:00Z",
            "end": "2026-05-01T00:01:00Z",
            "tweet_count": 3,
            "retrieved_at": "2026-06-01T00:00:00Z",
        },
        {
            "category": "btc_general",
            "start": "2026-05-01T00:10:00Z",
            "end": "2026-05-01T00:11:00Z",
            "tweet_count": 7,
            "retrieved_at": "2026-06-01T00:00:00Z",
        },
        {
            "category": "btc_general",
            "start": "2026-05-01T00:16:00Z",
            "end": "2026-05-01T00:17:00Z",
            "tweet_count": 100,
            "retrieved_at": "2026-06-01T00:00:00Z",
        },
    ]

    rows = materialize_x_signal_features(
        [{"ticker": "KXBTC15M-001", "decision_timestamp": "2026-05-01T00:15:00Z"}],
        counts,
        manifest,
    )

    assert rows[0]["x_counts_btc_general_15m"] == 10.0
    assert rows[0]["x_signal_max_source_event_timestamp_utc"] == "2026-05-01T00:11:00Z"
    assert rows[0]["x_signal_retrieved_at_utc"] == "2026-06-01T00:00:00Z"
    assert rows[0]["x_signal_manifest_id"] == "x_counts_test"

    with pytest.raises(XNoLookaheadError):
        validate_x_signal_feature_rows(
            [
                {
                    "decision_timestamp": "2026-05-01T00:15:00Z",
                    "x_signal_max_source_event_timestamp_utc": "2026-05-01T00:16:00Z",
                }
            ]
        )


def test_generate_minimal_x_features_uses_trailing_counts_only() -> None:
    counts = [
        {
            "category": "btc_general",
            "start": "2026-05-01T00:00:00Z",
            "end": "2026-05-01T00:01:00Z",
            "tweet_count": 3,
            "retrieved_at": "2026-06-01T00:00:00Z",
        },
        {
            "category": "btc_general",
            "start": "2026-05-01T00:10:00Z",
            "end": "2026-05-01T00:11:00Z",
            "tweet_count": 7,
            "retrieved_at": "2026-06-01T00:00:00Z",
        },
        {
            "category": "macro_rates",
            "start": "2026-05-01T00:14:00Z",
            "end": "2026-05-01T00:15:00Z",
            "tweet_count": 11,
            "retrieved_at": "2026-06-01T00:00:00Z",
        },
    ]

    rows = generate_minimal_x_features(
        [{"ticker": "KXBTC15M-001", "decision_timestamp": "2026-05-01T00:15:00Z"}],
        counts,
        windows_seconds=(300, 900),
    )

    assert rows[0]["x_counts_btc_general_5m"] == 7.0
    assert rows[0]["x_counts_btc_general_15m"] == 10.0
    assert rows[0]["x_counts_macro_rates_5m"] == 11.0
    assert rows[0]["x_total_count_15m"] == 21.0


def test_model_evaluation_ablation_reports_x_external_signal_context() -> None:
    rows = []
    for index in range(8):
        yes = index % 2
        signal = 2.0 if yes else 0.2
        rows.append(
            {
                "ticker": f"KXBTC15M-{index:03d}",
                "decision_timestamp": f"2026-05-01T{index:02d}:15:00Z",
                "decision_minute_offset": 12,
                "time_since_open_seconds": 720,
                "time_to_close_seconds": 180,
                "yes": yes,
                "x_counts_btc_general_15m": signal,
                "x_attention_btc_general_15m_vs_24h_z": signal / 2,
            }
        )
    manifest = {
        "dataset_id": "x_counts_test",
        "source_identity": "x_api",
        "query_catalog_version": "x_api.query_catalog.test.v1",
        "coverage": {"row_count": 12},
        "actual_cost": {"cost_usd": 0.02},
        "estimated_cost": {"cost_usd": 0.02},
        "artifact_hashes": {"counts_jsonl_sha256": "abc"},
        "suitability": "suitable_for_model_evaluation",
    }

    groups = resolve_feature_groups(
        [
            "decision_minute_offset",
            "time_since_open_seconds",
            "x_counts_btc_general_15m",
            "x_attention_btc_general_15m_vs_24h_z",
        ]
    )
    report = build_feature_ablation_report(
        rows,
        feature_columns=[
            "decision_minute_offset",
            "time_since_open_seconds",
            "x_counts_btc_general_15m",
            "x_attention_btc_general_15m_vs_24h_z",
        ],
        external_signal_manifest=manifest,
    )

    assert groups["x_external_signal_state"] == [
        "x_counts_btc_general_15m",
        "x_attention_btc_general_15m_vs_24h_z",
    ]
    assert any(item["name"] == "without_x_external_signal_state" for item in report["ablations"])
    assert report["external_signal_context"]["dataset_id"] == "x_counts_test"
    assert "does not authorize" in report["external_signal_context"]["non_promotion_notice"]


def test_real_x_collection_requires_only_daily_budget_and_uses_mocked_client(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 1, 1, tzinfo=UTC)

    with pytest.raises(XBudgetError):
        collect_x_counts_dataset(
            market="KXBTC15M",
            start=start,
            end=end,
            output_root=tmp_path / "research",
            budget=XCostBudget(daily_cap_usd=0.01),
            client=FixtureXCountsClient(),
            catalog=small_catalog(),
            source_mode="x_api_live",
        )

    result = collect_x_counts_dataset(
        market="KXBTC15M",
        start=start,
        end=end,
        output_root=tmp_path / "research",
        budget=approved_budget(),
        client=FixtureXCountsClient(),
        catalog=small_catalog(),
        source_mode="x_api_live",
    )

    assert result.manifest["actual_cost"]["cost_usd"] == pytest.approx(0.02)
    assert result.manifest["actual_cost"]["request_count"] == 2

    with pytest.raises(XCredentialError):
        HttpXCountsClient(bearer_token=None)


def test_external_signals_cli_loads_dotenv_without_overriding_shell_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "ALPHADB_X_API_DAILY_CAP_USD=4.25\n"
        "ALPHADB_X_BEARER_TOKEN=from-dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHADB_X_BEARER_TOKEN", "from-shell")

    values = env_with_dotenv(dotenv)

    assert values["ALPHADB_X_API_DAILY_CAP_USD"] == "4.25"
    assert values["ALPHADB_X_BEARER_TOKEN"] == "from-shell"
