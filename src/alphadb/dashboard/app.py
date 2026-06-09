"""Live-first AlphaDB operator console."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from alphadb.collectors.brti import (
    BRTI_INDEX_ID,
    DEFAULT_BRTI_FRESHNESS_LIMIT_SECONDS,
    BRTILatestContextRepository,
)
from alphadb.config import Settings, settings_from_env
from alphadb.dashboard.auth import DashboardAuthConfig, evaluate_access
from alphadb.dashboard.data_explorer import DashboardDataExplorerRepository
from alphadb.dashboard.lab import DashboardLabRepository, lab_entry_from_compile_result
from alphadb.dashboard.skills import (
    capabilities_payload,
    classify_terminal_request,
    terminal_response,
)
from alphadb.dashboard.strategy import DashboardStrategyRepository, compile_strategy_brief
from alphadb.health import HealthReport, collect_health
from alphadb.live_runtime import (
    EXPENSIVE_YES_LIVE_STRATEGY,
    FAIR_VALUE_LIVE_STRATEGY,
    LiveRunStatusRepository,
    LiveRuntimeConfig,
    LiveRuntimeConfigRepository,
    MARKET_CONTEXT_COINBASE_PRIMARY,
    runtime_strategy_metadata,
)
from alphadb.live_risk import LiveRiskAdmissionRepository
from alphadb.performance import PerformanceSummaryRepository
from alphadb.portfolio import cached_portfolio_balance_payload


ConfigRepositoryFactory = Callable[[str], LiveRuntimeConfigRepository]
StatusRepositoryFactory = Callable[[str], LiveRunStatusRepository]
LiveRiskRepositoryFactory = Callable[[str], LiveRiskAdmissionRepository]
StrategyRepositoryFactory = Callable[[str], DashboardStrategyRepository]
DataExplorerRepositoryFactory = Callable[[str], DashboardDataExplorerRepository]
LabRepositoryFactory = Callable[[str], DashboardLabRepository]
PerformanceRepositoryFactory = Callable[[str], PerformanceSummaryRepository]
HealthCollector = Callable[[Settings], HealthReport]
PortfolioBalanceProvider = Callable[[Settings], Mapping[str, Any]]
LIVE_DASHBOARD_STRATEGIES = (FAIR_VALUE_LIVE_STRATEGY, EXPENSIVE_YES_LIVE_STRATEGY)
LIVE_RISK_TIMEZONE = "America/Los_Angeles"


@dataclass(frozen=True)
class DashboardService:
    settings: Settings
    config_repository_factory: ConfigRepositoryFactory = LiveRuntimeConfigRepository
    status_repository_factory: StatusRepositoryFactory = LiveRunStatusRepository
    live_risk_repository_factory: LiveRiskRepositoryFactory = LiveRiskAdmissionRepository
    strategy_repository_factory: StrategyRepositoryFactory = DashboardStrategyRepository
    data_explorer_repository_factory: DataExplorerRepositoryFactory = (
        DashboardDataExplorerRepository
    )
    lab_repository_factory: LabRepositoryFactory = DashboardLabRepository
    performance_repository_factory: PerformanceRepositoryFactory = PerformanceSummaryRepository
    health_collector: HealthCollector = collect_health
    portfolio_balance_provider: PortfolioBalanceProvider = cached_portfolio_balance_payload

    def api_health(self) -> dict[str, Any]:
        report = self.health_collector(self.settings)
        return {
            "ok": report.ok,
            "environment": report.environment,
            "generated_at_utc": report.generated_at_utc.isoformat(),
            "components": report.as_rows(),
        }

    def live_payload(self, *, strategy: str = FAIR_VALUE_LIVE_STRATEGY) -> dict[str, Any]:
        strategy = _live_strategy(strategy)
        config_repository = self.config_repository_factory(self.settings.database_url)
        active = config_repository.seed_defaults(strategy=strategy)
        history = config_repository.recent_revisions(strategy=strategy, limit=6)
        status_repository = self.status_repository_factory(self.settings.database_url)
        latest_status = status_repository.latest_status(strategy=strategy)
        live_status = latest_status.as_dict()
        status_summary = _mapping_or_empty(live_status.get("summary"))
        live_status.pop("summary", None)
        report = self.health_collector(self.settings)
        return {
            "strategy": strategy,
            "strategies": [runtime_strategy_metadata(name) for name in LIVE_DASHBOARD_STRATEGIES],
            "strategy_metadata": runtime_strategy_metadata(strategy),
            "health": {
                "ok": report.ok,
                "environment": report.environment,
                "generated_at_utc": report.generated_at_utc.isoformat(),
                "components": report.as_rows(),
            },
            "active_config": active.as_dict(),
            "config_history": [revision.as_dict() for revision in history],
            "market_context": market_context_payload(
                settings=self.settings,
                active_config=active.config,
                latest_status_summary=status_summary,
            ),
            "portfolio_balance": dict(self.portfolio_balance_provider(self.settings)),
            "live_status": live_status,
            "recent_runs": status_repository.recent_details(
                strategy=strategy,
                limit=8,
            ),
        }

    def performance_payload(self, *, strategy: str = FAIR_VALUE_LIVE_STRATEGY) -> dict[str, Any]:
        strategy = _live_strategy(strategy)
        return dict(
            self.performance_repository_factory(self.settings.database_url).summary(
                strategy=strategy
            )
        )

    def save_config(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        strategy = _live_strategy(str(payload.get("strategy") or FAIR_VALUE_LIVE_STRATEGY))
        config_repository = self.config_repository_factory(self.settings.database_url)
        current = config_repository.seed_defaults(strategy=strategy).config
        config = LiveRuntimeConfig.from_payload(payload, current=current)
        saved = config_repository.save_config(
            config,
            strategy=strategy,
            created_by="dashboard",
        )
        return {
            "ok": True,
            "strategy": strategy,
            "strategy_metadata": runtime_strategy_metadata(strategy),
            "active_config": saved.as_dict(),
            "config_history": [
                revision.as_dict()
                for revision in config_repository.recent_revisions(
                    strategy=strategy,
                    limit=6,
                )
            ],
        }

    def reset_daily_limits(
        self,
        payload: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        strategy = _live_strategy(str(payload.get("strategy") or FAIR_VALUE_LIVE_STRATEGY))
        observed_at = _ensure_utc(now or datetime.now(UTC))
        live_risk_day = _live_risk_day(observed_at)
        repository = self.live_risk_repository_factory(self.settings.database_url)
        state = repository.get_state(strategy=strategy, live_risk_day=live_risk_day)
        if state is not None and state.status in {"locked", "reconciling"}:
            raise ValueError(f"cannot reset daily limits while risk state is {state.status}")
        previous_daily_loss = state.daily_loss_used_dollars if state else 0.0
        metadata = dict(state.metadata or {}) if state else {}
        reset_record = {
            "actor": str(payload.get("actor") or "dashboard"),
            "reset_at": observed_at.isoformat(),
            "previous_daily_loss_used_dollars": round(previous_daily_loss, 6),
            "preserved_open_exposure_dollars": round(
                state.open_exposure_dollars if state else 0.0,
                6,
            ),
            "preserved_pending_exposure_dollars": round(
                state.pending_exposure_dollars if state else 0.0,
                6,
            ),
        }
        metadata["last_daily_loss_reset"] = reset_record
        updated = repository.upsert_state(
            strategy=strategy,
            live_risk_day=live_risk_day,
            daily_loss_used_dollars=0.0,
            open_exposure_dollars=state.open_exposure_dollars if state else 0.0,
            pending_exposure_dollars=state.pending_exposure_dollars if state else 0.0,
            per_market_exposure_dollars=state.per_market_exposure_dollars if state else {},
            pending_reservations=state.pending_reservations if state else {},
            updated_at=observed_at,
            status=state.status if state else "active",
            metadata=metadata,
        )
        return {
            "ok": True,
            "strategy": strategy,
            "live_risk_day": live_risk_day.isoformat(),
            "reset": reset_record,
            "live_risk_admission_state": updated.as_dict(),
        }

    def compile_strategy(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        brief = str(payload.get("brief") or payload.get("ideaBrief") or "")
        title = payload.get("title")
        result = compile_strategy_brief(brief, title=str(title) if title else None).as_dict()
        if payload.get("route_unsupported_to_lab") and result["status"] == "unsupported":
            lab_entry = self._lab_repository().save_entry(**lab_entry_from_compile_result(result))
            result["lab_entry"] = lab_entry.as_dict()
        return result

    def list_strategies(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [
            strategy.as_dict()
            for strategy in self._strategy_repository().list_strategies(limit=limit)
        ]

    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        return self._strategy_repository().get_strategy(strategy_id).as_dict()

    def save_strategy(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or payload.get("title") or "Untitled strategy")
        brief = str(payload.get("brief") or payload.get("ideaBrief") or "")
        spec = payload.get("spec")
        compile_result: dict[str, Any] | None = None
        if not isinstance(spec, Mapping):
            compile_result = compile_strategy_brief(brief, title=name).as_dict()
            if compile_result["status"] == "unsupported":
                lab_entry = self._lab_repository().save_entry(
                    **lab_entry_from_compile_result(compile_result)
                )
                return {
                    "strategy": None,
                    "lab_entry": lab_entry.as_dict(),
                    "compile": compile_result,
                    "routed_to_lab": True,
                }
            spec = compile_result["spec"]
        if not isinstance(spec, Mapping):
            raise ValueError("strategy requires a spec or compilable brief")
        strategy = self._strategy_repository().save_strategy(
            strategy_id=_optional_text(payload.get("strategy_id")),
            name=name,
            brief=brief,
            spec=spec,
            status=str(payload.get("status") or "draft"),
            promotion_stage=str(payload.get("promotion_stage") or "draft"),
            metadata=_mapping_or_empty(payload.get("metadata")),
        )
        return {"strategy": strategy.as_dict(), "compile": compile_result}

    def list_data_views(self) -> list[dict[str, Any]]:
        return self._data_repository().list_views()

    def query_data_view(self, view_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._data_repository().query_view(
            view_name,
            filters=_mapping_or_empty(payload.get("filters")),
            sort=_mapping_or_empty(payload.get("sort")),
            limit=_int_payload(payload.get("limit"), default=100),
        )

    def save_data_view_to_lab(self, view_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        evidence = self._data_repository().evidence_from_view(
            view_name=view_name,
            filters=_mapping_or_empty(payload.get("filters")),
            sort=_mapping_or_empty(payload.get("sort")),
            limit=_int_payload(payload.get("limit"), default=100),
            metadata=_mapping_or_empty(payload.get("metadata")),
        )
        title = str(payload.get("title") or f"{evidence['view_label']} evidence")
        hypothesis = str(
            payload.get("hypothesis")
            or f"Saved evidence from {evidence['view_label']} for later strategy work."
        )
        entry = self._lab_repository().save_entry(
            title=title,
            hypothesis=hypothesis,
            brief=str(payload.get("brief") or ""),
            evidence=[evidence],
            metadata={
                "source": "data_explorer",
                "view_name": view_name,
                **_mapping_or_empty(payload.get("entry_metadata")),
            },
        )
        return {"entry": entry.as_dict(), "evidence": evidence}

    def export_data_view(self, view_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._data_repository().export_view(
            view_name,
            export_format=str(payload.get("format") or "csv"),
            filters=_mapping_or_empty(payload.get("filters")),
            sort=_mapping_or_empty(payload.get("sort")),
            limit=_int_payload(payload.get("limit"), default=100),
        )

    def list_lab_entries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [entry.as_dict() for entry in self._lab_repository().list_entries(limit=limit)]

    def get_lab_entry(self, lab_entry_id: str) -> dict[str, Any]:
        return {"entry": self._lab_repository().get_entry(lab_entry_id).as_dict()}

    def save_lab_entry(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        blockers = list(_sequence_of_mappings(payload.get("blockers")))
        for reason in _sequence_of_text(payload.get("unsupported_reasons")):
            blockers.append({"type": "unsupported_reason", "text": reason})
        for capability in _sequence_of_text(payload.get("missing_capabilities")):
            blockers.append({"type": "missing_capability", "name": capability})
        entry = self._lab_repository().save_entry(
            lab_entry_id=_optional_text(payload.get("lab_entry_id")),
            title=str(payload.get("title") or "Untitled lab entry"),
            hypothesis=str(payload.get("hypothesis") or ""),
            brief=str(payload.get("brief") or ""),
            status=str(payload.get("status") or "active"),
            verdict=_optional_text(payload.get("verdict")),
            blockers=blockers,
            evidence=_sequence_of_mappings(payload.get("evidence")),
            strategy=_mapping_or_empty(payload.get("strategy")),
            runs=_sequence_of_mappings(payload.get("runs")),
            notes=_sequence_of_mappings(payload.get("notes")),
            insights=_sequence_of_mappings(payload.get("insights")),
            metrics=_mapping_or_empty(payload.get("metrics")),
            metadata=_mapping_or_empty(payload.get("metadata")),
        )
        return entry.as_dict()

    def list_lab_insights(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [insight.as_dict() for insight in self._lab_repository().list_insights(limit=limit)]

    def capabilities(self) -> dict[str, Any]:
        return capabilities_payload()

    def ask_agent(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        skill, params = classify_terminal_request(payload)
        note = _optional_text(params.pop("note", None))
        if skill == "capabilities.list":
            result: Any = self.capabilities()
        elif skill == "live.summary":
            result = self.live_payload(
                strategy=_live_strategy(_optional_text(params.get("strategy")))
            )
        elif skill == "strategy.compile":
            result = self.compile_strategy(params)
        elif skill == "strategy.list":
            result = self.list_strategies(limit=_int_payload(params.get("limit"), default=25))
        elif skill == "data.views.list":
            result = self.list_data_views()
        elif skill == "data.view.query":
            view_name = str(params.get("view_name") or params.get("view") or "decisions")
            result = self.query_data_view(view_name, params)
        elif skill == "data.view.save_to_lab":
            view_name = str(params.get("view_name") or params.get("view") or "decisions")
            result = self.save_data_view_to_lab(view_name, params)
        elif skill == "lab.entries.list":
            result = self.list_lab_entries(limit=_int_payload(params.get("limit"), default=25))
        elif skill == "lab.insights.list":
            result = self.list_lab_insights(limit=_int_payload(params.get("limit"), default=20))
        else:
            raise KeyError(f"unknown skill: {skill}")
        return terminal_response(skill=skill, result=result, note=note)

    def _strategy_repository(self) -> DashboardStrategyRepository:
        return self.strategy_repository_factory(self.settings.database_url)

    def _data_repository(self) -> DashboardDataExplorerRepository:
        return self.data_explorer_repository_factory(self.settings.database_url)

    def _lab_repository(self) -> DashboardLabRepository:
        return self.lab_repository_factory(self.settings.database_url)


def market_context_payload(
    *,
    settings: Settings,
    active_config: LiveRuntimeConfig,
    latest_status_summary: Mapping[str, Any],
) -> dict[str, Any]:
    latest_run_context = _mapping_or_empty(latest_status_summary.get("market_context"))
    coinbase_diagnostics = _mapping_or_empty(latest_run_context.get("coinbase_diagnostics"))
    return {
        "active_source": active_config.market_context_source,
        "active_source_label": market_context_label(active_config.market_context_source),
        "latest_run": dict(latest_run_context),
        "brti_latest": brti_latest_context_payload(settings),
        "coinbase_diagnostics": dict(coinbase_diagnostics),
    }


def brti_latest_context_payload(settings: Settings) -> dict[str, Any]:
    freshness_seconds = DEFAULT_BRTI_FRESHNESS_LIMIT_SECONDS
    generated_at = datetime.now(UTC)
    try:
        status = BRTILatestContextRepository(settings.database_url).get_latest(
            index_id=BRTI_INDEX_ID,
            now=generated_at,
            freshness_limit=timedelta(seconds=freshness_seconds),
        )
    except Exception as exc:
        return {
            "index_id": BRTI_INDEX_ID,
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "generated_at": generated_at.isoformat(),
            "freshness_limit_seconds": freshness_seconds,
            "age_seconds": None,
            "value": None,
            "source_timestamp": None,
            "received_at": None,
            "source_lag_ms": None,
        }
    context = status.context
    return {
        "index_id": status.index_id,
        "status": status.status,
        "reason": status.reason,
        "generated_at": status.generated_at.isoformat(),
        "freshness_limit_seconds": freshness_seconds,
        "age_seconds": round(status.age_ms / 1000.0, 6)
        if status.age_ms is not None
        else None,
        "value": str(context.value) if context else None,
        "source_timestamp": context.source_timestamp.isoformat() if context else None,
        "received_at": context.received_at.isoformat() if context else None,
        "source_lag_ms": context.source_lag_ms if context else None,
        "raw_event_id": context.raw_event_id if context else None,
        "payload_hash": context.payload_hash if context else None,
    }


def market_context_label(source: str | None) -> str:
    labels = {
        MARKET_CONTEXT_COINBASE_PRIMARY: "Coinbase primary",
        "brti_primary": "BRTI primary",
        "fixture": "Fixture",
    }
    return labels.get(str(source or ""), str(source or MARKET_CONTEXT_COINBASE_PRIMARY))


def dashboard_auth_config(settings: Settings) -> DashboardAuthConfig:
    return DashboardAuthConfig.from_settings(settings).validate()


def _path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence_of_text(value: Any) -> Sequence[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _sequence_of_mappings(value: Any) -> Sequence[Mapping[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _int_payload(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _query_text(query: Mapping[str, Sequence[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    text = str(values[0]).strip()
    return text or None


def _live_strategy(value: str | None) -> str:
    strategy = str(value or FAIR_VALUE_LIVE_STRATEGY).strip() or FAIR_VALUE_LIVE_STRATEGY
    if strategy not in LIVE_DASHBOARD_STRATEGIES:
        raise ValueError(f"unsupported live strategy: {strategy}")
    return strategy


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _live_risk_day(value: datetime) -> date:
    return _ensure_utc(value).astimezone(ZoneInfo(LIVE_RISK_TIMEZONE)).date()


def _query_int(query: Mapping[str, Sequence[str]], key: str, default: int) -> int:
    value = _query_text(query, key)
    return default if value is None else int(value)


def _query_filters(query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    filter_keys = {
        "run_id",
        "market_ticker",
        "status",
        "outcome",
        "source",
        "strategy",
        "model_id",
        "dataset_id",
        "promotion_state",
        "decision_outcome",
        "created_after",
        "created_before",
        "decision_after",
        "decision_before",
    }
    filters: dict[str, Any] = {}
    for key in filter_keys:
        value = _query_text(query, key)
        if value is not None:
            filters[key] = value
    return filters


def _query_sort(query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    sort: dict[str, Any] = {}
    column = _query_text(query, "sort")
    direction = _query_text(query, "direction")
    if column:
        sort["column"] = column
    if direction:
        sort["direction"] = direction
    return sort


def _error_code(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return "not_found"
    if isinstance(exc, ValueError):
        return "bad_request"
    return "server_error"


def _error_status(exc: Exception) -> HTTPStatus:
    if isinstance(exc, KeyError):
        return HTTPStatus.NOT_FOUND
    if isinstance(exc, ValueError):
        return HTTPStatus.BAD_REQUEST
    return HTTPStatus.INTERNAL_SERVER_ERROR


def make_handler(service: DashboardService) -> type[BaseHTTPRequestHandler]:
    auth_config = dashboard_auth_config(service.settings)

    class DashboardRequestHandler(BaseHTTPRequestHandler):
        server_version = "AlphaDBDashboard/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/healthz":
                self._json({"ok": True})
                return
            if path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            if path == "/api/live":
                if not self._authenticated():
                    self._json(
                        {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED
                    )
                    return
                self._json(
                    service.live_payload(
                        strategy=_live_strategy(_query_text(parse_qs(parsed.query), "strategy"))
                    )
                )
                return
            if path.startswith("/api/"):
                if not self._authenticated():
                    self._json_error("unauthorized", status=HTTPStatus.UNAUTHORIZED)
                    return
                self._dispatch_api_get(path, parse_qs(parsed.query))
                return
            if path == "/":
                if not self._authenticated():
                    self._html(login_html(), status=HTTPStatus.UNAUTHORIZED)
                    return
                self._html(DASHBOARD_HTML)
                return
            self._json_error("not_found", status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/auth/login":
                self._login()
                return
            if path == "/api/live/config":
                if not self._authenticated():
                    self._json(
                        {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED
                    )
                    return
                try:
                    payload = json.loads(self._body().decode("utf-8"))
                    if not isinstance(payload, Mapping):
                        raise ValueError("request body must be a JSON object")
                    query_strategy = _query_text(parse_qs(parsed.query), "strategy")
                    effective_payload = dict(payload)
                    if query_strategy is not None:
                        effective_payload["strategy"] = query_strategy
                    self._json(service.save_config(effective_payload))
                except Exception as exc:
                    self._json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if path.startswith("/api/"):
                if not self._authenticated():
                    self._json_error("unauthorized", status=HTTPStatus.UNAUTHORIZED)
                    return
                try:
                    payload = self._json_body()
                    self._dispatch_api_post(path, payload)
                except Exception as exc:
                    self._json_error(str(exc), code=_error_code(exc), status=_error_status(exc))
                return
            self._json_error("not_found", status=HTTPStatus.NOT_FOUND)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors_headers()
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _login(self) -> None:
            form = parse_qs(self._body().decode("utf-8"))
            pin = form.get("pin", [""])[0]
            decision = evaluate_access(auth_config, submitted_pin=pin)
            if not decision.authenticated or not decision.remember_token:
                self._html(login_html(error="Invalid PIN"), status=HTTPStatus.UNAUTHORIZED)
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                cookie_header(
                    auth_config.cookie_name,
                    decision.remember_token,
                    max_age=auth_config.cookie_ttl_seconds,
                ),
            )
            self.end_headers()

        def _authenticated(self) -> bool:
            if not auth_config.enabled:
                return True
            token = cookie_value(self.headers.get("Cookie"), auth_config.cookie_name)
            return evaluate_access(auth_config, remember_token=token).authenticated

        def _body(self) -> bytes:
            size = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(size)

        def _json_body(self) -> Mapping[str, Any]:
            body = self._body()
            if not body:
                return {}
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("request body must be a JSON object")
            return payload

        def _dispatch_api_get(self, path: str, query: Mapping[str, Sequence[str]]) -> None:
            try:
                if path == "/api/health":
                    self._json_ok(service.api_health())
                    return
                if path == "/api/performance":
                    self._json_ok(
                        service.performance_payload(
                            strategy=_live_strategy(_query_text(query, "strategy"))
                        )
                    )
                    return
                if path == "/api/strategies":
                    self._json_ok(
                        {
                            "strategies": service.list_strategies(
                                limit=_query_int(query, "limit", 50)
                            )
                        }
                    )
                    return
                if path.startswith("/api/strategies/"):
                    parts = _path_parts(path)
                    if len(parts) == 3:
                        self._json_ok({"strategy": service.get_strategy(parts[2])})
                        return
                if path == "/api/data/views":
                    self._json_ok({"views": service.list_data_views()})
                    return
                if path.startswith("/api/data/views/"):
                    parts = _path_parts(path)
                    if len(parts) == 4:
                        self._json_ok(
                            service.query_data_view(
                                parts[3],
                                {
                                    "filters": _query_filters(query),
                                    "sort": _query_sort(query),
                                    "limit": _query_int(query, "limit", 100),
                                },
                            )
                        )
                        return
                if path == "/api/lab/entries":
                    self._json_ok(
                        {"entries": service.list_lab_entries(limit=_query_int(query, "limit", 50))}
                    )
                    return
                if path.startswith("/api/lab/entries/"):
                    parts = _path_parts(path)
                    if len(parts) == 4:
                        self._json_ok(service.get_lab_entry(parts[3]))
                        return
                if path == "/api/lab/insights":
                    self._json_ok(
                        {
                            "insights": service.list_lab_insights(
                                limit=_query_int(query, "limit", 20)
                            )
                        }
                    )
                    return
                if path == "/api/capabilities":
                    self._json_ok(service.capabilities())
                    return
                self._json_error("not_found", status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._json_error(str(exc), code=_error_code(exc), status=_error_status(exc))

        def _dispatch_api_post(self, path: str, payload: Mapping[str, Any]) -> None:
            if path == "/api/strategies/compile":
                self._json_ok(service.compile_strategy(payload))
                return
            if path == "/api/strategies":
                data = service.save_strategy(payload)
                status = HTTPStatus.ACCEPTED if data.get("routed_to_lab") else HTTPStatus.OK
                self._json_ok(data, status=status)
                return
            if path.startswith("/api/data/views/"):
                parts = _path_parts(path)
                if len(parts) == 5 and parts[4] == "export":
                    self._json_ok({"export": service.export_data_view(parts[3], payload)})
                    return
                if len(parts) == 5 and parts[4] == "save-to-lab":
                    self._json_ok(service.save_data_view_to_lab(parts[3], payload))
                    return
            if path == "/api/lab/entries":
                self._json_ok({"entry": service.save_lab_entry(payload)})
                return
            if path == "/api/ask":
                self._json_ok(service.ask_agent(payload))
                return
            if path == "/api/live/reset-daily-limits":
                self._json_ok(service.reset_daily_limits(payload))
                return
            self._json_error("not_found", status=HTTPStatus.NOT_FOUND)

        def _json(
            self,
            payload: Mapping[str, Any],
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json_ok(
            self,
            data: Any,
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self._json({"ok": True, "data": data}, status=status)

        def _json_error(
            self,
            message: str,
            *,
            code: str = "error",
            status: HTTPStatus = HTTPStatus.BAD_REQUEST,
        ) -> None:
            self._json(
                {"ok": False, "error": {"code": code, "message": message}},
                status=status,
            )

        def _html(self, html: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    return DashboardRequestHandler


def cookie_value(header: str | None, name: str) -> str | None:
    if not header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    morsel = cookie.get(name)
    return None if morsel is None else morsel.value


def cookie_header(name: str, value: str, *, max_age: int) -> str:
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]["max-age"] = str(max_age)
    cookie[name]["path"] = "/"
    cookie[name]["httponly"] = True
    cookie[name]["samesite"] = "Lax"
    return cookie.output(header="").strip()


def login_html(*, error: str | None = None) -> str:
    error_html = f"<p class='login-error'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AlphaDB</title>
  <style>{BASE_CSS}</style>
</head>
<body class="login-body">
  <main class="login-panel">
    <h1>AlphaDB</h1>
    <form method="post" action="/auth/login">
      <label for="pin">PIN</label>
      <input id="pin" name="pin" type="password" inputmode="numeric" maxlength="4" autofocus>
      {error_html}
      <button type="submit">Unlock</button>
    </form>
  </main>
</body>
</html>"""


BASE_CSS = """
:root {
  color-scheme: dark;
  --bg: #080b0d;
  --panel: #11171a;
  --panel-2: #151d21;
  --line: #263238;
  --text: #edf3f4;
  --muted: #8da1a8;
  --green: #5ee2a0;
  --amber: #f6c85f;
  --red: #f07178;
  --blue: #7dc7ff;
  --input: #0b1114;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  letter-spacing: 0;
}
button, input { font: inherit; }
.login-body { display: grid; place-items: center; padding: 24px; }
.login-panel {
  width: min(360px, 100%);
  border: 1px solid var(--line);
  background: var(--panel);
  padding: 24px;
  border-radius: 8px;
}
.login-panel h1 { margin: 0 0 20px; font-size: 24px; }
.login-panel label { display: block; color: var(--muted); margin-bottom: 8px; }
.login-panel input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--input);
  color: var(--text);
  padding: 12px;
}
.login-panel button, .save-button {
  border: 0;
  border-radius: 6px;
  background: var(--green);
  color: #06100b;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
}
.login-panel button { width: 100%; margin-top: 16px; }
.login-error, .error { color: var(--red); }
"""


DASHBOARD_CSS = (
    BASE_CSS
    + """
.shell {
  display: grid;
  grid-template-columns: 212px minmax(0, 1fr);
  min-height: 100vh;
}
.nav {
  border-right: 1px solid var(--line);
  background: #0a0f12;
  padding: 16px 12px;
}
.brand { font-size: 18px; font-weight: 800; margin: 4px 8px 18px; }
.nav a {
  display: block;
  color: var(--muted);
  text-decoration: none;
  padding: 9px 10px;
  border-radius: 6px;
  margin-bottom: 4px;
}
.nav a.active {
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--line);
}
.main { min-width: 0; }
.topbar {
  min-height: 58px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 18px;
  background: #0b1013;
  gap: 12px;
}
.topbar h1 { font-size: 19px; margin: 0; }
.status-strip { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.pill {
  border: 1px solid var(--line);
  color: var(--muted);
  background: var(--panel);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
}
.pill.good { color: var(--green); }
.pill.warn { color: var(--amber); }
.pill.bad { color: var(--red); }
.content { padding: 16px 18px 28px; }
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, .9fr);
  gap: 14px;
}
.panel {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 8px;
  padding: 14px;
  min-width: 0;
}
.panel h2 {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--muted);
  font-weight: 700;
  text-transform: uppercase;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
}
.metric {
  border: 1px solid var(--line);
  background: var(--panel-2);
  border-radius: 6px;
  padding: 12px;
  min-height: 82px;
}
.label { color: var(--muted); font-size: 12px; margin-bottom: 7px; }
.value { font-size: 24px; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.detail { color: var(--muted); font-size: 12px; margin-top: 6px; min-height: 16px; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.field label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}
.field input {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--input);
  color: var(--text);
  padding: 8px 10px;
}
.field .error { min-height: 16px; font-size: 12px; margin-top: 4px; }
.save-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}
.save-state { min-height: 18px; color: var(--muted); font-size: 12px; }
.lower {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, .75fr);
  gap: 14px;
  margin-top: 14px;
}
table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 12px;
}
.table-scroll {
  overflow-x: auto;
}
.attempts-table {
  min-width: 880px;
}
th, td {
  border-bottom: 1px solid var(--line);
  text-align: left;
  padding: 8px 6px;
  vertical-align: top;
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-weight: 700; }
@media (max-width: 920px) {
  .shell { grid-template-columns: 1fr; }
  .nav { display: flex; align-items: center; gap: 8px; border-right: 0; border-bottom: 1px solid var(--line); }
  .brand { margin: 0 10px 0 0; }
  .nav a { margin-bottom: 0; }
  .grid, .lower { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .form-grid { grid-template-columns: 1fr; }
}
"""
)


DASHBOARD_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AlphaDB Live</title>
  <style>{DASHBOARD_CSS}</style>
</head>
<body>
  <div class="shell">
    <nav class="nav">
      <div class="brand">AlphaDB</div>
      <a class="active" href="/">Live</a>
    </nav>
    <main class="main">
      <header class="topbar">
        <h1>Live Operator Console</h1>
        <div class="status-strip">
          <span class="pill" id="env-pill">env</span>
          <span class="pill" id="health-pill">health</span>
          <span class="pill" id="orders-pill">live orders</span>
          <span class="pill" id="config-pill">config</span>
        </div>
      </header>
      <section class="content">
        <div class="grid">
          <section class="panel">
            <h2>Live State</h2>
            <div class="summary-grid">
              <div class="metric"><div class="label">Market</div><div class="value" id="market">--</div><div class="detail" id="run-id">--</div></div>
              <div class="metric"><div class="label">Decision</div><div class="value" id="decision">--</div><div class="detail" id="decision-detail">--</div></div>
              <div class="metric"><div class="label">Risk</div><div class="value" id="risk">--</div><div class="detail" id="risk-detail">--</div></div>
              <div class="metric"><div class="label">Execution</div><div class="value" id="execution">--</div><div class="detail" id="execution-detail">--</div></div>
            </div>
          </section>
          <section class="panel">
            <h2>Runtime Config</h2>
            <form id="config-form" novalidate>
              <div class="form-grid">
                <div class="field"><label for="live-strategy">Strategy</label><select id="live-strategy" name="strategy"><option value="fair_value_live">Fair-value live</option><option value="expensive_yes_live">Expensive YES guarded live run</option></select><div class="error" data-error-for="strategy"></div></div>
                <div class="field"><label for="max_order_dollars">Max order dollars</label><input id="max_order_dollars" name="max_order_dollars" type="number" min="0.01" step="0.01"><div class="error" data-error-for="max_order_dollars"></div></div>
                <div class="field"><label for="max_market_exposure_dollars">Max market exposure dollars</label><input id="max_market_exposure_dollars" name="max_market_exposure_dollars" type="number" min="0.01" step="0.01"><div class="error" data-error-for="max_market_exposure_dollars"></div></div>
                <div class="field"><label for="max_daily_loss_dollars">Max daily loss dollars</label><input id="max_daily_loss_dollars" name="max_daily_loss_dollars" type="number" min="0.01" step="0.01"><div class="error" data-error-for="max_daily_loss_dollars"></div></div>
                <div class="field"><label for="min_edge">Min edge</label><input id="min_edge" name="min_edge" type="number" min="0" max="1" step="0.0001"><div class="error" data-error-for="min_edge"></div></div>
                <div class="field"><label for="min_contract_price" id="threshold-label">Min contract price</label><input id="min_contract_price" name="min_contract_price" type="number" min="0" max="1" step="0.01"><div class="error" data-error-for="min_contract_price"></div></div>
                <div class="field"><label for="max_markets">Max markets</label><input id="max_markets" name="max_markets" type="number" min="1" max="500" step="1"><div class="error" data-error-for="max_markets"></div></div>
              </div>
              <div class="save-row"><button class="save-button" type="submit">Save</button><span class="save-state" id="save-state"></span></div>
            </form>
          </section>
        </div>
        <div class="lower">
          <section class="panel">
            <h2>Recent Attempts</h2>
            <div class="table-scroll"><table class="attempts-table"><thead><tr><th>Time</th><th>Market</th><th>Status</th><th>Reason</th><th>Ask</th><th>Edge</th><th>Min</th><th>Gap</th><th>Fill</th></tr></thead><tbody id="attempts-body"></tbody></table></div>
          </section>
          <section class="panel">
            <h2>Config History</h2>
            <table><thead><tr><th>Version</th><th>Order</th><th>Exposure</th><th>Daily</th><th id="history-threshold-label">Min price</th><th>Saved</th></tr></thead><tbody id="history-body"></tbody></table>
          </section>
        </div>
      </section>
    </main>
  </div>
  <script>
const fields = ["max_order_dollars","max_market_exposure_dollars","max_daily_loss_dollars","min_edge","min_contract_price","max_markets"];
function selectedStrategy() {{ return document.getElementById("live-strategy").value || "fair_value_live"; }}
function text(id, value) {{ document.getElementById(id).textContent = value ?? "--"; }}
function cls(id, name) {{ document.getElementById(id).className = name; }}
function money(value) {{ const n = Number(value || 0); return "$" + n.toFixed(2); }}
function pctValue(number) {{ return (number * 100).toFixed(2) + "%"; }}
function pct(value) {{
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return pctValue(number);
}}
function edgeAttribution(row) {{
  return row.live_edge_attribution && typeof row.live_edge_attribution === "object" ? row.live_edge_attribution : {{}};
}}
function edgeGap(attr) {{
  const shortfall = Number(attr.edge_shortfall);
  if (Number.isFinite(shortfall) && shortfall > 0) return "short " + pctValue(shortfall);
  const margin = Number(attr.edge_margin);
  if (Number.isFinite(margin)) return (margin >= 0 ? "+" : "") + pctValue(margin);
  const edge = Number(attr.edge);
  const minEdge = Number(attr.min_edge);
  if (Number.isFinite(edge) && Number.isFinite(minEdge)) {{
    const derivedMargin = edge - minEdge;
    if (derivedMargin < 0) return "short " + pctValue(-derivedMargin);
    return "+" + pctValue(derivedMargin);
  }}
  return "--";
}}
function shortTime(value) {{
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {{ month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }});
}}
function setErrors(errors) {{
  document.querySelectorAll("[data-error-for]").forEach(el => el.textContent = "");
  Object.entries(errors).forEach(([key, value]) => {{
    const el = document.querySelector(`[data-error-for="${{key}}"]`);
    if (el) el.textContent = value;
  }});
}}
function validate(payload) {{
  const errors = {{}};
  ["max_order_dollars","max_market_exposure_dollars","max_daily_loss_dollars"].forEach(key => {{
    if (!Number.isFinite(payload[key]) || payload[key] <= 0) errors[key] = "Must be positive.";
  }});
  if (!Number.isFinite(payload.min_edge) || payload.min_edge < 0 || payload.min_edge > 1) errors.min_edge = "Use 0 through 1.";
  if (!Number.isFinite(payload.min_contract_price) || payload.min_contract_price < 0 || payload.min_contract_price > 1) errors.min_contract_price = "Use 0 through 1.";
  if (!Number.isInteger(payload.max_markets) || payload.max_markets < 1 || payload.max_markets > 500) errors.max_markets = "Use 1 through 500.";
  return errors;
}}
async function loadLive() {{
  const res = await fetch("/api/live?strategy=" + encodeURIComponent(selectedStrategy()));
  const data = await res.json();
  render(data);
}}
function render(data) {{
  const status = data.live_status || {{}};
  const config = data.active_config || {{}};
  const metadata = data.strategy_metadata || {{}};
  if (data.strategy) document.getElementById("live-strategy").value = data.strategy;
  text("threshold-label", metadata.threshold_label || "Min contract price");
  text("history-threshold-label", metadata.threshold_label || "Min price");
  text("env-pill", data.health?.environment || "env");
  text("health-pill", data.health?.ok ? "health ok" : "health error");
  cls("health-pill", "pill " + (data.health?.ok ? "good" : "bad"));
  text("orders-pill", status.live_orders_enabled ? "live runner active" : "live runner inactive");
  cls("orders-pill", "pill " + (status.live_orders_enabled ? "good" : "bad"));
  text("config-pill", (metadata.label || status.strategy || "strategy") + " · config v" + (config.version ?? "--"));
  text("market", status.current_market_ticker || "No run");
  text("run-id", status.run_id || "no recent run");
  text("decision", status.decision_outcome || "--");
  text("decision-detail", status.selected_side || status.skip_reason || "--");
  text("risk", money(status.daily_loss_used_dollars));
  text("risk-detail", "daily loss limit " + money(status.daily_loss_limit_dollars) + " · market " + money(status.market_exposure_used_dollars) + " / " + money(status.market_exposure_limit_dollars));
  text("execution", status.latest_attempt_status || status.fill_status || "--");
  text("execution-detail", status.latest_attempt_reason || status.fill_status || "--");
  fields.forEach(key => {{ if (key in config) document.getElementById(key).value = config[key]; }});
  const attempts = status.recent_attempts || [];
  document.getElementById("attempts-body").innerHTML = attempts.length ? attempts.map(row => {{
    const edge = edgeAttribution(row);
    return `<tr><td>${{shortTime(row.submitted_at || row.created_at)}}</td><td>${{row.market_ticker || ""}}</td><td>${{row.status || ""}}</td><td>${{row.reason || row.guard_reason || ""}}</td><td>${{row.observed_yes_ask ?? ""}}</td><td>${{pct(edge.edge)}}</td><td>${{pct(edge.min_edge)}}</td><td>${{edgeGap(edge)}}</td><td>${{row.fill_status || ""}}</td></tr>`;
  }}).join("") : "<tr><td colspan='9'>No recent attempts</td></tr>";
  const history = data.config_history || [];
  document.getElementById("history-body").innerHTML = history.map(row => `<tr><td>${{row.version}}</td><td>${{money(row.max_order_dollars)}}</td><td>${{money(row.max_market_exposure_dollars)}}</td><td>${{money(row.max_daily_loss_dollars)}}</td><td>${{money(row.min_contract_price)}}</td><td>${{shortTime(row.created_at)}}</td></tr>`).join("");
}}
document.getElementById("config-form").addEventListener("submit", async event => {{
  event.preventDefault();
  const payload = Object.fromEntries(fields.map(key => [key, key === "max_markets" ? Number.parseInt(document.getElementById(key).value, 10) : Number.parseFloat(document.getElementById(key).value)]));
  payload.strategy = selectedStrategy();
  const errors = validate(payload);
  setErrors(errors);
  if (Object.keys(errors).length) return;
  text("save-state", "Saving...");
  const res = await fetch("/api/live/config?strategy=" + encodeURIComponent(selectedStrategy()), {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(payload) }});
  const data = await res.json();
  if (!res.ok || data.ok === false) {{
    text("save-state", data.error || "Save failed");
    return;
  }}
  text("save-state", "Saved");
  await loadLive();
}});
document.getElementById("live-strategy").addEventListener("change", () => loadLive().catch(error => text("save-state", error.message)));
loadLive().catch(error => text("save-state", error.message));
  </script>
</body>
</html>"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    port = args.port or int(settings.dashboard_port)
    service = DashboardService(settings=settings)
    server = ThreadingHTTPServer((args.host, port), make_handler(service))
    print(f"alphadb-dashboard listening on http://{args.host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
