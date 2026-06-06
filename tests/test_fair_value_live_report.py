from __future__ import annotations

import json
import os
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from alphadb.model_evaluation import fair_value_live_report as report_module
from alphadb.model_evaluation.fair_value_live_report import (
    Boto3FairValueLiveEvidenceClient,
    FairValueLiveReportConfig,
    FairValueLiveReportError,
    FairValueLiveReportGenerator,
)


class FailingEvidenceClient:
    aws_profile = "alphadb"
    aws_region = "us-east-2"
    ec2_metadata_disabled = True

    def get_caller_identity(self) -> dict[str, Any]:
        raise FairValueLiveReportError(
            surface="sts",
            kind="dns_resolution_failed",
            message="Could not resolve host: sts.us-east-2.amazonaws.com",
        )

    def describe_rule(self, name: str) -> dict[str, Any]:
        raise FairValueLiveReportError(
            surface=f"eventbridge:{name}",
            kind="dns_resolution_failed",
            message="Could not resolve host: events.us-east-2.amazonaws.com",
        )

    def list_targets_by_rule(self, name: str) -> list[dict[str, Any]]:
        raise FairValueLiveReportError(
            surface=f"eventbridge-targets:{name}",
            kind="dns_resolution_failed",
            message="Could not resolve host: events.us-east-2.amazonaws.com",
        )

    def filter_log_events(
        self,
        *,
        log_group_name: str,
        start: datetime,
        end: datetime,
        filter_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        raise FairValueLiveReportError(
            surface=f"cloudwatch:{log_group_name}",
            kind="dns_resolution_failed",
            message="Could not resolve host: logs.us-east-2.amazonaws.com",
        )

    def list_stopped_tasks(self, *, cluster: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        raise FairValueLiveReportError(
            surface=f"ecs:{cluster}",
            kind="dns_resolution_failed",
            message="Could not resolve host: ecs.us-east-2.amazonaws.com",
        )

    def list_s3_run_prefixes(self, *, bucket: str, prefix: str) -> list[str]:
        raise FairValueLiveReportError(
            surface=f"s3:{bucket}/{prefix}",
            kind="dns_resolution_failed",
            message="Could not resolve host: s3.us-east-2.amazonaws.com",
        )

    def load_s3_json(self, *, bucket: str, key: str) -> dict[str, Any]:
        raise AssertionError("no S3 JSON should be loaded when listing fails")


class EndpointFailingEvidenceClient(FailingEvidenceClient):
    def _endpoint_error(self, surface: str) -> FairValueLiveReportError:
        return FairValueLiveReportError(
            surface=surface,
            kind="endpoint_connectivity_failed",
            message="Could not connect to the endpoint URL",
        )

    def get_caller_identity(self) -> dict[str, Any]:
        raise self._endpoint_error("sts")

    def describe_rule(self, name: str) -> dict[str, Any]:
        raise self._endpoint_error(f"eventbridge:{name}")

    def list_targets_by_rule(self, name: str) -> list[dict[str, Any]]:
        raise self._endpoint_error(f"eventbridge-targets:{name}")

    def filter_log_events(
        self,
        *,
        log_group_name: str,
        start: datetime,
        end: datetime,
        filter_pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        raise self._endpoint_error(f"cloudwatch:{log_group_name}")

    def list_stopped_tasks(self, *, cluster: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        raise self._endpoint_error(f"ecs:{cluster}")

    def list_s3_run_prefixes(self, *, bucket: str, prefix: str) -> list[str]:
        raise self._endpoint_error(f"s3:{bucket}/{prefix}")


def test_report_distinguishes_dns_block_from_generic_endpoint_block() -> None:
    report = FairValueLiveReportGenerator(
        client=FailingEvidenceClient(),
        config=FairValueLiveReportConfig(retry_delays_seconds=()),
    ).generate(
        start=datetime(2026, 6, 6, 17, 15, tzinfo=UTC),
        end=datetime(2026, 6, 6, 17, 30, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["block_reason"] == "dns_resolution_failed"
    assert report["aws_config"] == {
        "profile": "alphadb",
        "region": "us-east-2",
        "ec2_metadata_disabled": True,
    }
    assert report["summary"]["run_count"] == 0
    assert report["summary"]["orders"] == {
        "submitted": 0,
        "skipped": 0,
        "rejected": 0,
        "errors": 0,
        "filled_contracts": 0,
    }
    assert {surface["status"] for surface in report["surfaces"].values()} == {"failed"}
    assert {surface["failure_kind"] for surface in report["surfaces"].values()} == {
        "dns_resolution_failed"
    }


def test_report_distinguishes_endpoint_block_from_dns_block() -> None:
    report = FairValueLiveReportGenerator(
        client=EndpointFailingEvidenceClient(),
        config=FairValueLiveReportConfig(retry_delays_seconds=()),
    ).generate(
        start=datetime(2026, 6, 6, 17, 15, tzinfo=UTC),
        end=datetime(2026, 6, 6, 17, 30, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["block_reason"] == "endpoint_connectivity_failed"
    assert {surface["failure_kind"] for surface in report["surfaces"].values()} == {
        "endpoint_connectivity_failed"
    }


class S3OnlyEvidenceClient(FailingEvidenceClient):
    def get_caller_identity(self) -> dict[str, Any]:
        return {"Account": "766780331843"}

    def list_s3_run_prefixes(self, *, bucket: str, prefix: str) -> list[str]:
        return [f"{prefix}/fv_live_20260606T171540Z/"]

    def load_s3_json(self, *, bucket: str, key: str) -> dict[str, Any]:
        artifact = key.rsplit("/", 1)[-1]
        if artifact == "manifest.json":
            return {
                "run_id": "fv_live_20260606T171540Z",
                "generated_at": "2026-06-06T17:15:40+00:00",
                "one_cycle": True,
                "hot_path_scope": "one_current_decision_no_replay_no_walk_forward_no_full_history",
                "runtime_config": {
                    "config_id": "live_cfg_deaa1bcf8660",
                    "version": 4,
                    "source": "dashboard_postgres",
                    "snapshot": {
                        "max_order_dollars": 10,
                        "max_market_exposure_dollars": 15,
                        "max_daily_loss_dollars": 100,
                        "min_edge": 0,
                        "min_contract_price": 0.25,
                        "max_markets": 20,
                    },
                },
                "runtime_controls": {
                    "runtime_guard": {
                        "credentials_present": True,
                        "can_submit_live_orders": True,
                    }
                },
                "executable_quote": {
                    "source": "kalshi_orderbook",
                    "freshness": {"quote_age_seconds": 0.0},
                },
                "live_risk_admission_state": {
                    "status": "missing",
                    "read_reason": "risk_state_not_required",
                },
                "selected_decision": {
                    "decision": "skip",
                    "reason": "edge_below_min",
                },
            }
        if artifact == "live_order_attempts.json":
            return {
                "attempts": [
                    {
                        "status": "skipped",
                        "reason": "edge_below_min",
                        "market_ticker": "KXBTC15M-26JUN061315-15",
                    }
                ]
            }
        if artifact == "live_reconciliation_report.json":
            return {
                "settlement": {
                    "status": "reconciled",
                    "settled_rows": 0,
                    "unsettled_rows": 0,
                },
                "pnl": {
                    "filled_contracts": 0,
                    "gross_cost_dollars": 0,
                    "fees_dollars": 0,
                    "payout_dollars": 0,
                    "net_pnl_dollars": 0,
                    "unsettled_exposure_dollars": 0,
                },
                "rows": [
                    {
                        "order_status": "skipped",
                        "settlement_status": "no_fill",
                    }
                ],
            }
        if artifact == "decision_rows.json":
            return {"rows": [{"quote_source": "kalshi_orderbook"}]}
        raise AssertionError(f"unexpected key: {key}")


class FlakyS3EvidenceClient(S3OnlyEvidenceClient):
    def __init__(self) -> None:
        self.s3_list_attempts = 0

    def list_s3_run_prefixes(self, *, bucket: str, prefix: str) -> list[str]:
        self.s3_list_attempts += 1
        if self.s3_list_attempts == 1:
            raise FairValueLiveReportError(
                surface=f"s3:{bucket}/{prefix}",
                kind="endpoint_connectivity_failed",
                message="Could not connect to the endpoint URL",
            )
        return super().list_s3_run_prefixes(bucket=bucket, prefix=prefix)


def test_report_uses_reachable_s3_artifacts_for_partial_zero_order_report() -> None:
    report = FairValueLiveReportGenerator(
        client=S3OnlyEvidenceClient(),
        config=FairValueLiveReportConfig(retry_delays_seconds=()),
    ).generate(
        start=datetime(2026, 6, 6, 17, 15, tzinfo=UTC),
        end=datetime(2026, 6, 6, 17, 30, tzinfo=UTC),
    )

    assert report["status"] == "partial"
    assert "s3_artifacts" not in report["missing_surfaces"]
    assert report["summary"]["run_count"] == 1
    assert report["summary"]["config"]["config_id"] == "live_cfg_deaa1bcf8660"
    assert report["summary"]["runtime_guard"]["credentials_present"] is True
    assert report["summary"]["executable_quote"]["source"] == "kalshi_orderbook"
    assert report["summary"]["one_cycle"] is True
    assert report["summary"]["orders"] == {
        "submitted": 0,
        "skipped": 1,
        "rejected": 0,
        "errors": 0,
        "filled_contracts": 0,
        "skip_reasons": {"edge_below_min": 1},
    }
    assert report["summary"]["reconciliation"]["net_pnl_dollars"] == 0.0
    assert report["runs"][0]["selected_decision"]["reason"] == "edge_below_min"


def test_report_retries_transient_endpoint_failure_before_using_s3_artifacts() -> None:
    client = FlakyS3EvidenceClient()

    report = FairValueLiveReportGenerator(
        client=client,
        config=FairValueLiveReportConfig(retry_delays_seconds=(0,)),
    ).generate(
        start=datetime(2026, 6, 6, 17, 15, tzinfo=UTC),
        end=datetime(2026, 6, 6, 17, 30, tzinfo=UTC),
    )

    assert client.s3_list_attempts == 2
    assert report["surfaces"]["s3_artifacts"]["attempts"] == 2
    assert report["summary"]["run_count"] == 1


def test_fair_value_live_report_has_public_console_command() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["alphadb-fair-value-live-report"]
        == "alphadb.model_evaluation.fair_value_live_report:main"
    )


def test_boto3_adapter_configures_local_aws_profile_region_and_metadata(monkeypatch) -> None:
    sessions: list[dict[str, str]] = []

    class FakeSession:
        def __init__(self, *, profile_name: str, region_name: str):
            sessions.append({"profile": profile_name, "region": region_name})

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(Session=FakeSession))
    monkeypatch.delenv("AWS_EC2_METADATA_DISABLED", raising=False)

    client = Boto3FairValueLiveEvidenceClient(
        aws_profile="alphadb",
        aws_region="us-east-2",
        ec2_metadata_disabled=True,
    )

    assert sessions == [{"profile": "alphadb", "region": "us-east-2"}]
    assert client.ec2_metadata_disabled is True
    assert os.environ["AWS_EC2_METADATA_DISABLED"] == "true"


def test_cli_emits_blocked_json_when_sso_dns_fails_before_sts(monkeypatch, capsys) -> None:
    class SsoDnsFailureClient:
        def __init__(self, **kwargs: Any):
            raise RuntimeError(
                "NameResolutionError: Failed to resolve "
                "'portal.sso.us-east-1.amazonaws.com'"
            )

    monkeypatch.setattr(report_module, "Boto3FairValueLiveEvidenceClient", SsoDnsFailureClient)

    exit_code = report_module.main(
        [
            "--start",
            "2026-06-06T17:30:00Z",
            "--end",
            "2026-06-06T17:45:00Z",
            "--retry-delays-seconds",
            "",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "blocked"
    assert payload["block_reason"] == "dns_resolution_failed"
    assert payload["surfaces"]["aws_client_setup"] == {
        "status": "failed",
        "attempts": 1,
        "failure_kind": "dns_resolution_failed",
        "message": (
            "NameResolutionError: Failed to resolve "
            "'portal.sso.us-east-1.amazonaws.com'"
        ),
    }
    assert payload["summary"]["run_count"] == 0
    assert payload["summary"]["orders"]["submitted"] == 0


def test_deployment_docs_name_report_command_as_scheduler_entrypoint() -> None:
    docs = Path("docs/deployment/live-money-cutover-checklist.md").read_text(encoding="utf-8")

    assert "alphadb-fair-value-live-report" in docs
