"""Settlement-state readiness contracts and fixtures."""

from alphadb.settlement.dataset import (
    SETTLEMENT_STATE_DATASET_SUMMARY_SCHEMA_VERSION,
    SettlementDatasetBuildResult,
    SettlementDatasetMarketInput,
    SettlementDatasetSummary,
    build_settlement_state_dataset,
)
from alphadb.settlement.fixtures import SyntheticSettlementFixtureCase, kxbtc15m_synthetic_fixture_suite
from alphadb.settlement.inputs import (
    MarketSettlementMetadata,
    NormalizedOfficialSettlementInput,
    OfficialSettlementPrint,
    SettlementInputSource,
    SettlementInputValidationError,
    expected_final_window_times,
    validated_final_window_prints,
)
from alphadb.settlement.manifest import (
    SETTLEMENT_STATE_MANIFEST_SCHEMA_VERSION,
    SettlementReadinessManifest,
    build_settlement_readiness_manifest,
    write_settlement_readiness_manifest,
)
from alphadb.settlement.state import (
    SETTLEMENT_STATE_ROW_SCHEMA_VERSION,
    SettlementStateRow,
    calculate_settlement_state,
    calculate_settlement_state_from_payloads,
)

__all__ = [
    "MarketSettlementMetadata",
    "NormalizedOfficialSettlementInput",
    "OfficialSettlementPrint",
    "SETTLEMENT_STATE_DATASET_SUMMARY_SCHEMA_VERSION",
    "SETTLEMENT_STATE_MANIFEST_SCHEMA_VERSION",
    "SETTLEMENT_STATE_ROW_SCHEMA_VERSION",
    "SettlementInputSource",
    "SettlementInputValidationError",
    "SettlementDatasetBuildResult",
    "SettlementDatasetMarketInput",
    "SettlementDatasetSummary",
    "SettlementReadinessManifest",
    "SettlementStateRow",
    "SyntheticSettlementFixtureCase",
    "build_settlement_readiness_manifest",
    "build_settlement_state_dataset",
    "calculate_settlement_state",
    "calculate_settlement_state_from_payloads",
    "expected_final_window_times",
    "kxbtc15m_synthetic_fixture_suite",
    "validated_final_window_prints",
    "write_settlement_readiness_manifest",
]
