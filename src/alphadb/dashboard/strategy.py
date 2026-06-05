"""Strategy Brief, Strategy Spec, and dashboard persistence helpers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.state.repository import OperationalStateRepository


SPEC_SCHEMA_VERSION = "strategy_spec/v1"
SUPPORTED_MARKET_SERIES = {"KXBTC15M"}
SUPPORTED_TEMPLATES = {
    "fair_value",
    "model_probability",
    "structural_threshold",
    "momentum_reversal",
    "external_signal_threshold",
}
MAX_BRIEF_LENGTH = 8_000


@dataclass(frozen=True)
class StrategyTemplate:
    template_id: str
    label: str
    keywords: tuple[str, ...]
    default_inputs: tuple[str, ...]
    belief_type: str

    def score(self, text: str) -> int:
        return sum(1 for keyword in self.keywords if keyword in text)


TEMPLATES: tuple[StrategyTemplate, ...] = (
    StrategyTemplate(
        template_id="fair_value",
        label="Fair Value",
        keywords=(
            "fair value",
            "implied",
            "mispriced",
            "expected value",
            "probability",
            "edge",
        ),
        default_inputs=("kalshi_quotes", "coinbase_btc_price", "threshold_distance"),
        belief_type="fair_value_edge",
    ),
    StrategyTemplate(
        template_id="model_probability",
        label="Model Probability",
        keywords=(
            "model",
            "ml",
            "machine learning",
            "classifier",
            "artifact",
            "calibration",
            "predict",
        ),
        default_inputs=("model_registry_probability", "feature_row", "kalshi_quotes"),
        belief_type="model_probability_edge",
    ),
    StrategyTemplate(
        template_id="structural_threshold",
        label="Structural Threshold",
        keywords=(
            "structural",
            "threshold",
            "strike",
            "distance",
            "spread",
            "liquidity",
            "order book",
        ),
        default_inputs=("kalshi_quotes", "threshold_distance", "market_metadata"),
        belief_type="rule_threshold",
    ),
    StrategyTemplate(
        template_id="momentum_reversal",
        label="Momentum / Reversal",
        keywords=(
            "momentum",
            "trend",
            "reversal",
            "mean reversion",
            "volatility",
            "breakout",
            "range",
        ),
        default_inputs=("coinbase_btc_candles", "volatility", "threshold_distance"),
        belief_type="market_structure_signal",
    ),
    StrategyTemplate(
        template_id="external_signal_threshold",
        label="External Signal Threshold",
        keywords=(
            "funding",
            "funding reversal",
            "funding reversals",
            "whale",
            "on-chain",
            "sentiment",
            "news",
            "weather",
            "discord",
            "twitter",
            "x api",
        ),
        default_inputs=("external_signal", "coinbase_btc_price", "kalshi_quotes"),
        belief_type="external_signal_threshold",
    ),
)

UNSUPPORTED_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("portfolio", "portfolio_optimizer", "Portfolio-level allocation is not an MVP template."),
    ("basket", "portfolio_optimizer", "Basket trading is not an MVP template."),
    ("options", "options_market", "Options execution is outside the Kalshi MVP scope."),
    ("maker", "maker_execution", "Maker execution is deferred behind a later execution policy."),
    ("limit order", "maker_execution", "Resting limit-order logic is not an MVP action."),
    ("train", "model_training", "Training models from the dashboard is not an MVP action."),
    ("reinforcement", "rl_policy", "Reinforcement learning policies are not an MVP template."),
    ("arbitrage", "cross_venue_arbitrage", "Cross-venue arbitrage is not an MVP template."),
)


@dataclass(frozen=True)
class SpecCompileResult:
    status: str
    brief: str
    title: str
    selected_template: str | None
    confidence: float
    spec: dict[str, Any] | None
    missing_fields: tuple[str, ...]
    questions: tuple[str, ...]
    unsupported_reasons: tuple[str, ...]
    closest_templates: tuple[str, ...]
    missing_capabilities: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "brief": self.brief,
            "title": self.title,
            "selected_template": self.selected_template,
            "confidence": self.confidence,
            "spec": self.spec,
            "missing_fields": list(self.missing_fields),
            "questions": list(self.questions),
            "unsupported_reasons": list(self.unsupported_reasons),
            "closest_templates": list(self.closest_templates),
            "missing_capabilities": list(self.missing_capabilities),
        }


@dataclass(frozen=True)
class DashboardStrategy:
    strategy_id: str
    name: str
    brief: str
    spec: Mapping[str, Any]
    status: str
    promotion_stage: str
    metadata: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "brief": self.brief,
            "spec": dict(self.spec),
            "status": self.status,
            "promotion_stage": self.promotion_stage,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def compile_strategy_brief(brief: str, *, title: str | None = None) -> SpecCompileResult:
    clean_brief = _clean_brief(brief)
    text = clean_brief.lower()
    inferred_title = title or _title_from_brief(clean_brief)
    unsupported = [
        reason for keyword, _capability, reason in UNSUPPORTED_KEYWORDS if keyword in text
    ]
    missing_capabilities = [
        capability for keyword, capability, _reason in UNSUPPORTED_KEYWORDS if keyword in text
    ]
    ranked_templates = _rank_templates(text)
    selected = ranked_templates[0] if ranked_templates else None
    closest = tuple(template.template_id for template in ranked_templates[:3])
    missing_fields: list[str] = []
    questions: list[str] = []

    if not clean_brief:
        return SpecCompileResult(
            status="needs_confirmation",
            brief="",
            title=inferred_title,
            selected_template=None,
            confidence=0.0,
            spec=None,
            missing_fields=("brief",),
            questions=("What is the trading thesis?",),
            unsupported_reasons=(),
            closest_templates=(),
            missing_capabilities=(),
        )

    if selected is None:
        return SpecCompileResult(
            status="unsupported",
            brief=clean_brief,
            title=inferred_title,
            selected_template=None,
            confidence=0.18,
            spec=None,
            missing_fields=(),
            questions=(
                "Which supported template is closest: fair value, model probability, structural threshold, momentum reversal, or external signal threshold?",
            ),
            unsupported_reasons=tuple(unsupported)
            or ("No supported strategy template matched the brief.",),
            closest_templates=tuple(template.template_id for template in TEMPLATES[:3]),
            missing_capabilities=tuple(missing_capabilities) or ("strategy_template",),
        )

    market_series = _extract_market_series(text)
    decision_minute = _extract_decision_minute(text)
    min_edge = _extract_min_edge(text)
    max_order_dollars = _extract_dollars(text, default=5.0)
    if market_series is None:
        market_series = "KXBTC15M"
        missing_fields.append("market.series")
        questions.append("Should this run on KXBTC15M 15-minute BTC markets?")
    if decision_minute is None:
        decision_minute = 12
    if min_edge is None:
        min_edge = 0.01
        missing_fields.append("trade_policy.min_edge")
        questions.append("What minimum edge should the strategy require before acting?")

    confidence = min(0.92, 0.45 + 0.12 * selected.score(text))
    if missing_fields:
        confidence = min(confidence, 0.64)
    if unsupported:
        confidence = min(confidence, 0.42)

    spec = _build_spec(
        selected,
        brief=clean_brief,
        market_series=market_series,
        decision_minute=decision_minute,
        min_edge=min_edge,
        max_order_dollars=max_order_dollars,
    )
    status = "unsupported" if unsupported else ("needs_confirmation" if missing_fields else "supported")
    if status == "unsupported":
        spec = None

    return SpecCompileResult(
        status=status,
        brief=clean_brief,
        title=inferred_title,
        selected_template=selected.template_id,
        confidence=round(confidence, 2),
        spec=spec,
        missing_fields=tuple(missing_fields),
        questions=tuple(questions),
        unsupported_reasons=tuple(unsupported),
        closest_templates=closest,
        missing_capabilities=tuple(missing_capabilities),
    )


def validate_strategy_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, Mapping):
        raise ValueError("strategy spec must be a JSON object")
    normalized = dict(spec)
    if normalized.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise ValueError(f"strategy spec schema_version must be {SPEC_SCHEMA_VERSION}")
    template = _text(normalized.get("template"))
    if template not in SUPPORTED_TEMPLATES:
        raise ValueError(f"unsupported strategy template: {template}")
    market = _mapping(normalized.get("market"))
    series = _text(market.get("series"))
    if series not in SUPPORTED_MARKET_SERIES:
        raise ValueError(f"unsupported market series: {series}")
    cadence = _int(market.get("cadence_minutes"), default=15)
    if cadence != 15:
        raise ValueError("MVP strategy specs require a 15-minute cadence")
    decision_minute = _int(market.get("decision_minute"), default=12)
    if decision_minute < 0 or decision_minute > 14:
        raise ValueError("decision_minute must be between 0 and 14")
    inputs = normalized.get("inputs")
    if not isinstance(inputs, Sequence) or isinstance(inputs, (str, bytes)):
        raise ValueError("strategy spec inputs must be a JSON array")
    if not inputs:
        raise ValueError("strategy spec requires at least one input")
    if len(inputs) > 16:
        raise ValueError("strategy spec allows at most 16 inputs")
    for item in inputs:
        if not isinstance(item, Mapping) or not _text(item.get("name")):
            raise ValueError("each strategy spec input requires a name")
    trade_policy = _mapping(normalized.get("trade_policy"))
    execution = _text(trade_policy.get("execution"))
    if execution != "taker_ioc":
        raise ValueError("MVP strategy specs only allow taker_ioc execution")
    min_edge = _float(trade_policy.get("min_edge"), default=0.0)
    if min_edge < 0 or min_edge > 1:
        raise ValueError("trade_policy.min_edge must be between 0 and 1")
    max_order = _float(trade_policy.get("max_order_dollars"), default=0.0)
    if max_order <= 0:
        raise ValueError("trade_policy.max_order_dollars must be positive")
    normalized["market"] = {
        **market,
        "series": series,
        "cadence_minutes": cadence,
        "decision_minute": decision_minute,
    }
    normalized["trade_policy"] = {
        **trade_policy,
        "execution": execution,
        "min_edge": min_edge,
        "max_order_dollars": max_order,
    }
    return json.loads(json.dumps(normalized, sort_keys=True, default=str))


def strategy_spec_hash(spec: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(validate_strategy_spec(spec)).encode("utf-8")).hexdigest()


class DashboardStrategyRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def list_strategies(self, *, limit: int = 50) -> list[DashboardStrategy]:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from dashboard_strategies
                    order by updated_at desc, strategy_id
                    limit %s
                    """,
                    (_bounded_limit(limit),),
                )
                rows = cursor.fetchall()
        return [_strategy_from_row(row) for row in rows]

    def get_strategy(self, strategy_id: str) -> DashboardStrategy:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select * from dashboard_strategies where strategy_id = %s",
                    (strategy_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"unknown strategy: {strategy_id}")
        return _strategy_from_row(row)

    def save_strategy(
        self,
        *,
        name: str,
        brief: str,
        spec: Mapping[str, Any],
        strategy_id: str | None = None,
        status: str = "draft",
        promotion_stage: str = "draft",
        metadata: Mapping[str, Any] | None = None,
    ) -> DashboardStrategy:
        normalized_spec = validate_strategy_spec(spec)
        if status not in {"draft", "active", "archived"}:
            raise ValueError("strategy status must be draft, active, or archived")
        strategy_id = strategy_id or f"strat_{uuid4().hex[:12]}"
        clean_name = _clean_text(name, default="Untitled strategy", max_length=160)
        clean_brief = _clean_brief(brief)
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into dashboard_strategies (
                        strategy_id, name, brief, spec, status, promotion_stage, metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (strategy_id) do update set
                        name = excluded.name,
                        brief = excluded.brief,
                        spec = excluded.spec,
                        status = excluded.status,
                        promotion_stage = excluded.promotion_stage,
                        metadata = excluded.metadata,
                        updated_at = now()
                    returning *
                    """,
                    (
                        strategy_id,
                        clean_name,
                        clean_brief,
                        Jsonb(normalized_spec),
                        status,
                        promotion_stage,
                        Jsonb(dict(metadata or {})),
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("strategy save returned no row")
        return _strategy_from_row(row)

def _build_spec(
    template: StrategyTemplate,
    *,
    brief: str,
    market_series: str,
    decision_minute: int,
    min_edge: float,
    max_order_dollars: float,
) -> dict[str, Any]:
    return {
        "schema_version": SPEC_SCHEMA_VERSION,
        "template": template.template_id,
        "market": {
            "series": market_series,
            "cadence_minutes": 15,
            "decision_minute": decision_minute,
        },
        "inputs": [
            {"name": input_name, "source": _input_source(input_name), "required": True}
            for input_name in template.default_inputs
        ],
        "belief": {
            "type": template.belief_type,
            "side_logic": "choose_best_side_when_edge_exceeds_minimum",
            "brief_summary": brief[:320],
        },
        "trade_policy": {
            "execution": "taker_ioc",
            "side": "best",
            "min_edge": round(min_edge, 4),
            "max_order_dollars": round(max_order_dollars, 2),
            "skip_conditions": [
                "missing_required_input",
                "edge_below_minimum",
                "risk_limit_reached",
            ],
        },
        "risk": {
            "max_market_exposure_dollars": round(max_order_dollars, 2),
            "max_daily_loss_dollars": round(max(max_order_dollars * 10, 1.0), 2),
        },
        "metadata": {
            "compiler": "deterministic_v1",
            "source": "strategy_brief",
        },
    }


def _input_source(input_name: str) -> str:
    if input_name.startswith("kalshi") or input_name == "market_metadata":
        return "kalshi"
    if input_name.startswith("coinbase") or input_name in {"volatility", "threshold_distance"}:
        return "market_data"
    if input_name.startswith("model") or input_name == "feature_row":
        return "model_registry"
    return "external"


def _rank_templates(text: str) -> list[StrategyTemplate]:
    ranked = sorted(TEMPLATES, key=lambda template: template.score(text), reverse=True)
    return [template for template in ranked if template.score(text) > 0]


def _extract_market_series(text: str) -> str | None:
    if "kxbtc15m" in text or ("btc" in text and ("15m" in text or "15-minute" in text)):
        return "KXBTC15M"
    return None


def _extract_decision_minute(text: str) -> int | None:
    match = re.search(r"(?:minute|minute\s+)(\d{1,2})", text)
    if match:
        value = int(match.group(1))
        if 0 <= value <= 14:
            return value
    match = re.search(r"(\d{1,2})\s*(?:min|minute)s?\s*(?:in|after)", text)
    if match:
        value = int(match.group(1))
        if 0 <= value <= 14:
            return value
    return None


def _extract_min_edge(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:c|cent|cents)\s+edge", text)
    if match:
        return float(match.group(1)) / 100
    match = re.search(
        r"edge\s*(?:is\s+)?(?:>|>=|over|above|of)?\s*(\d+(?:\.\d+)?)\s*%",
        text,
    )
    if match:
        return float(match.group(1)) / 100
    return None


def _extract_dollars(text: str, *, default: float) -> float:
    match = re.search(r"\$(\d+(?:\.\d+)?)", text)
    if match:
        return max(0.01, float(match.group(1)))
    return default


def _title_from_brief(brief: str) -> str:
    words = brief.strip().split()
    if not words:
        return "Untitled strategy"
    title = " ".join(words[:8]).strip(" .,;:")
    return title[:80] or "Untitled strategy"


def _clean_brief(brief: str) -> str:
    return _clean_text(brief, default="", max_length=MAX_BRIEF_LENGTH)


def _clean_text(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    return (text or default)[:max_length]


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise ValueError("strategy spec requires nested JSON objects")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _float(value: Any, *, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit), 200))


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _strategy_from_row(row: Mapping[str, Any]) -> DashboardStrategy:
    return DashboardStrategy(
        strategy_id=str(row["strategy_id"]),
        name=str(row["name"]),
        brief=str(row["brief"]),
        spec=_json_mapping(row["spec"]),
        status=str(row["status"]),
        promotion_stage=str(row["promotion_stage"]),
        metadata=_json_mapping(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _json_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise ValueError("expected JSON object from dashboard strategy repository")


def json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [json_ready(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
