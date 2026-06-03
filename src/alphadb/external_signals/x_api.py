"""X API counts research datasets and no-lookahead feature materialization."""

from __future__ import annotations

import json
import math
import re
import time
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib import error, parse, request

X_SOURCE_IDENTITY = "x_api"
X_COUNTS_SCHEMA_VERSION = "x_api.counts.v1"
X_MANIFEST_SCHEMA_VERSION = "external_signal_feature_set_manifest.v1"
DEFAULT_X_QUERY_CATALOG_VERSION = "x_api.query_catalog.kxbtc15m.v1"
DEFAULT_COUNT_WINDOWS_SECONDS = (60, 300, 900, 3600, 14_400, 86_400)
IGNORED_ARTIFACT_ROOT_NAMES = {"artifacts", "data", "research"}

EndpointFamily = Literal["counts_recent", "counts_all"]
Granularity = Literal["minute", "hour", "day"]


class XSignalError(ValueError):
    """Base class for X external-signal research errors."""


class XQueryCatalogError(XSignalError):
    """Raised when an X query catalog is invalid."""


class XBudgetError(XSignalError):
    """Raised when an X research run lacks safe budget approval."""


class XCredentialError(XSignalError):
    """Raised when live X credentials are missing or unsafe."""


class XResponseError(XSignalError):
    """Raised when an X counts response cannot be normalized."""


class XArtifactLocationError(XSignalError):
    """Raised when generated X artifacts would be written into public Git paths."""


class XNoLookaheadError(XSignalError):
    """Raised when X features would use source events after decision time."""


@dataclass(frozen=True)
class XEndpointProfile:
    family: EndpointFamily
    path: str
    request_unit_cost_usd: float
    max_days_per_request: int
    query_length_limit: int
    allowed_granularities: tuple[Granularity, ...]
    docs_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "path": self.path,
            "request_unit_cost_usd": self.request_unit_cost_usd,
            "max_days_per_request": self.max_days_per_request,
            "query_length_limit": self.query_length_limit,
            "allowed_granularities": list(self.allowed_granularities),
            "docs_url": self.docs_url,
        }


ENDPOINT_PROFILES: dict[EndpointFamily, XEndpointProfile] = {
    "counts_recent": XEndpointProfile(
        family="counts_recent",
        path="/2/tweets/counts/recent",
        request_unit_cost_usd=0.005,
        max_days_per_request=7,
        query_length_limit=512,
        allowed_granularities=("minute", "hour", "day"),
        docs_url="https://docs.x.com/x-api/posts/get-count-of-recent-posts",
    ),
    "counts_all": XEndpointProfile(
        family="counts_all",
        path="/2/tweets/counts/all",
        request_unit_cost_usd=0.010,
        max_days_per_request=31,
        query_length_limit=1024,
        allowed_granularities=("minute", "hour", "day"),
        docs_url="https://docs.x.com/x-api/posts/get-count-of-all-posts",
    ),
}


@dataclass(frozen=True)
class XQueryCategory:
    name: str
    query: str
    description: str
    endpoint_family: EndpointFamily = "counts_all"
    granularity: Granularity = "minute"
    enabled: bool = True

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z0-9_]+", self.name):
            raise XQueryCatalogError(f"invalid X query category name: {self.name!r}")
        if not self.query.strip():
            raise XQueryCatalogError(f"X query category {self.name} has an empty query")
        profile = ENDPOINT_PROFILES.get(self.endpoint_family)
        if profile is None:
            raise XQueryCatalogError(
                f"X query category {self.name} uses unknown endpoint {self.endpoint_family!r}"
            )
        if self.granularity not in profile.allowed_granularities:
            raise XQueryCatalogError(
                f"X query category {self.name} uses unsupported granularity {self.granularity!r}"
            )
        if len(self.query) > profile.query_length_limit:
            raise XQueryCatalogError(
                f"X query category {self.name} query length {len(self.query)} exceeds "
                f"{profile.query_length_limit} for {self.endpoint_family}"
            )

    def as_dict(self, *, include_query: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "endpoint_family": self.endpoint_family,
            "granularity": self.granularity,
            "enabled": self.enabled,
        }
        if include_query:
            payload["query"] = self.query
        return payload


@dataclass(frozen=True)
class XQueryCatalog:
    version: str
    categories: tuple[XQueryCategory, ...]

    def validate(self) -> None:
        if not self.version:
            raise XQueryCatalogError("X query catalog version is required")
        seen: set[str] = set()
        for category in self.categories:
            category.validate()
            if category.name in seen:
                raise XQueryCatalogError(f"duplicate X query category: {category.name}")
            seen.add(category.name)
        if not any(category.enabled for category in self.categories):
            raise XQueryCatalogError("X query catalog must enable at least one category")

    def enabled_categories(self, names: Sequence[str] | None = None) -> tuple[XQueryCategory, ...]:
        self.validate()
        requested = set(names or ())
        if requested:
            known = {category.name for category in self.categories}
            unknown = sorted(requested.difference(known))
            if unknown:
                raise XQueryCatalogError(f"unknown X query categories: {', '.join(unknown)}")
        return tuple(
            category
            for category in self.categories
            if category.enabled and (not requested or category.name in requested)
        )

    def as_dict(self, *, include_queries: bool = True) -> dict[str, Any]:
        return {
            "version": self.version,
            "categories": [
                category.as_dict(include_query=include_queries)
                for category in self.categories
            ],
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> XQueryCatalog:
        raw_categories = payload.get("categories")
        if not isinstance(raw_categories, list):
            raise XQueryCatalogError("X query catalog must contain a categories list")
        categories: list[XQueryCategory] = []
        for raw in raw_categories:
            if not isinstance(raw, Mapping):
                raise XQueryCatalogError("X query catalog categories must be objects")
            categories.append(
                XQueryCategory(
                    name=str(raw.get("name", "")),
                    query=str(raw.get("query", "")),
                    description=str(raw.get("description", "")),
                    endpoint_family=str(raw.get("endpoint_family", "counts_all")),  # type: ignore[arg-type]
                    granularity=str(raw.get("granularity", "minute")),  # type: ignore[arg-type]
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        catalog = cls(version=str(payload.get("version", "")), categories=tuple(categories))
        catalog.validate()
        return catalog


DEFAULT_X_QUERY_CATALOG = XQueryCatalog(
    version=DEFAULT_X_QUERY_CATALOG_VERSION,
    categories=(
        XQueryCategory(
            name="btc_general",
            description="General English-language Bitcoin conversation volume.",
            query="(bitcoin OR btc) lang:en -is:retweet",
        ),
        XQueryCategory(
            name="btc_breaking",
            description="Bitcoin posts that look like breaking news or alerts.",
            query='(bitcoin OR btc) (breaking OR alert OR news OR "just in") lang:en -is:retweet',
        ),
        XQueryCategory(
            name="macro_rates",
            description="Macro and rates terms that may move BTC risk appetite.",
            query="(Fed OR FOMC OR CPI OR inflation OR rates OR yields OR dollar) lang:en -is:retweet",
        ),
        XQueryCategory(
            name="crypto_market_structure",
            description="Crypto market-structure stress and flow terms.",
            query=(
                "(bitcoin OR btc OR crypto) "
                "(liquidation OR liquidations OR ETF OR funding OR \"open interest\") "
                "lang:en -is:retweet"
            ),
        ),
        XQueryCategory(
            name="coinbase_official_status",
            description="Official Coinbase and Coinbase support/status conversation.",
            query=(
                "(from:Coinbase OR from:CoinbaseAssets OR from:CoinbaseSupport OR "
                "from:CoinbaseExch) (bitcoin OR BTC OR outage OR status OR trading) -is:retweet"
            ),
        ),
        XQueryCategory(
            name="exchange_outage",
            description="Major crypto exchange incident and outage conversation.",
            query=(
                "(coinbase OR binance OR kraken OR bybit) "
                "(outage OR degraded OR halted OR maintenance OR incident) lang:en -is:retweet"
            ),
        ),
        XQueryCategory(
            name="kalshi_prediction_market",
            description="Optional Kalshi and prediction-market Bitcoin context.",
            query='(Kalshi OR "prediction market" OR "prediction markets") (bitcoin OR BTC OR crypto) lang:en -is:retweet',
        ),
    ),
)


@dataclass(frozen=True)
class XCostBudget:
    daily_cap_usd: float

    def validate(self) -> None:
        if self.daily_cap_usd <= 0:
            raise XBudgetError("X daily budget cap must be positive")

    def as_dict(self) -> dict[str, float]:
        return {
            "daily_cap_usd": self.daily_cap_usd,
        }


@dataclass(frozen=True)
class XCostEstimateLine:
    category: str
    endpoint_family: EndpointFamily
    endpoint_path: str
    granularity: Granularity
    chunk_count: int
    request_unit_cost_usd: float
    estimated_cost_usd: float
    query_length: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "endpoint_family": self.endpoint_family,
            "endpoint_path": self.endpoint_path,
            "granularity": self.granularity,
            "chunk_count": self.chunk_count,
            "request_unit_cost_usd": self.request_unit_cost_usd,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "query_length": self.query_length,
        }


@dataclass(frozen=True)
class XCostEstimateReport:
    schema_version: str
    market: str
    start_time: datetime
    end_time: datetime
    query_catalog_version: str
    lines: tuple[XCostEstimateLine, ...]
    budget: XCostBudget | None
    budget_status: Literal["approved", "rejected"]
    rejection_reasons: tuple[str, ...]

    @property
    def estimated_request_count(self) -> int:
        return sum(line.chunk_count for line in self.lines)

    @property
    def estimated_cost_usd(self) -> float:
        return sum(line.estimated_cost_usd for line in self.lines)

    def assert_approved(self) -> None:
        if self.budget_status != "approved":
            raise XBudgetError(
                "X cost estimate is not approved: " + "; ".join(self.rejection_reasons)
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "market": self.market,
            "start_time": format_utc(self.start_time),
            "end_time": format_utc(self.end_time),
            "query_catalog_version": self.query_catalog_version,
            "estimated_request_count": self.estimated_request_count,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "budget": self.budget.as_dict() if self.budget is not None else None,
            "budget_status": self.budget_status,
            "rejection_reasons": list(self.rejection_reasons),
            "endpoint_profiles": {
                family: profile.as_dict() for family, profile in ENDPOINT_PROFILES.items()
            },
            "source_docs": sorted(
                {ENDPOINT_PROFILES[line.endpoint_family].docs_url for line in self.lines}
            ),
            "lines": [line.as_dict() for line in self.lines],
        }


class XCountsClient(Protocol):
    def get_counts(
        self,
        *,
        category_name: str,
        endpoint_family: EndpointFamily,
        query: str,
        start: datetime,
        end: datetime,
        granularity: Granularity,
        next_token: str | None = None,
    ) -> Mapping[str, Any]:
        """Return an X API counts response."""


class HttpXCountsClient:
    """Small urllib-backed client for X counts endpoints."""

    def __init__(
        self,
        *,
        bearer_token: str | None,
        base_url: str = "https://api.x.com",
        timeout_seconds: float = 20.0,
        max_attempts: int = 8,
        sleep_seconds: float = 5.0,
        max_rate_limit_sleep_seconds: float = 900.0,
    ):
        if not bearer_token:
            raise XCredentialError("X_BEARER_TOKEN or ALPHADB_X_BEARER_TOKEN is required")
        self.bearer_token = bearer_token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.sleep_seconds = max(0.0, sleep_seconds)
        self.max_rate_limit_sleep_seconds = max(0.0, max_rate_limit_sleep_seconds)

    def get_counts(
        self,
        *,
        category_name: str,
        endpoint_family: EndpointFamily,
        query: str,
        start: datetime,
        end: datetime,
        granularity: Granularity,
        next_token: str | None = None,
    ) -> Mapping[str, Any]:
        profile = ENDPOINT_PROFILES[endpoint_family]
        params = {
            "query": query,
            "start_time": format_utc(start),
            "end_time": format_utc(end),
            "granularity": granularity,
        }
        if next_token:
            params["next_token"] = next_token
        url = f"{self.base_url}{profile.path}?{parse.urlencode(params)}"
        http_request = request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.bearer_token}",
                "User-Agent": "alphadb/0.1",
            },
            method="GET",
        )
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, Mapping):
                    raise XResponseError("X counts response must be a JSON object")
                return payload
            except error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.max_attempts:
                    break
                time.sleep(self.retry_sleep_seconds(exc))
            except error.URLError as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                time.sleep(self.sleep_seconds)
        raise XResponseError(f"X counts request failed for {category_name}: {last_error}")

    def retry_sleep_seconds(self, exc: error.HTTPError) -> float:
        retry_after = exc.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), self.max_rate_limit_sleep_seconds)
            except ValueError:
                pass
        reset = exc.headers.get("x-rate-limit-reset")
        if reset:
            try:
                wait = float(reset) - time.time() + 2.0
                return min(max(wait, self.sleep_seconds), self.max_rate_limit_sleep_seconds)
            except ValueError:
                pass
        return self.sleep_seconds


class FixtureXCountsClient:
    """Fixture client for tests and public demos; it never touches the network."""

    def __init__(self, payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None):
        self.payloads = {
            category: list(responses) for category, responses in (payloads or {}).items()
        }
        self.calls: list[dict[str, Any]] = []
        self._call_index: dict[str, int] = defaultdict(int)

    def get_counts(
        self,
        *,
        category_name: str,
        endpoint_family: EndpointFamily,
        query: str,
        start: datetime,
        end: datetime,
        granularity: Granularity,
        next_token: str | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "category_name": category_name,
                "endpoint_family": endpoint_family,
                "query": query,
                "start": start,
                "end": end,
                "granularity": granularity,
                "next_token": next_token,
            }
        )
        responses = self.payloads.get(category_name)
        if responses is not None:
            index = self._call_index[category_name]
            self._call_index[category_name] += 1
            if index >= len(responses):
                raise XResponseError(f"fixture payload exhausted for {category_name}")
            return responses[index]
        return generate_fixture_counts_payload(category_name, start=start, end=end, granularity=granularity)


@dataclass(frozen=True)
class XCountsBucket:
    source_identity: str
    schema_version: str
    query_catalog_version: str
    category: str
    endpoint_family: EndpointFamily
    granularity: Granularity
    start: datetime
    end: datetime
    tweet_count: int
    retrieved_at: datetime
    request_id: str
    payload_hash: str

    @property
    def source_event_timestamp(self) -> datetime:
        return self.end

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_identity": self.source_identity,
            "schema_version": self.schema_version,
            "query_catalog_version": self.query_catalog_version,
            "category": self.category,
            "endpoint_family": self.endpoint_family,
            "granularity": self.granularity,
            "start": format_utc(self.start),
            "end": format_utc(self.end),
            "source_event_timestamp": format_utc(self.source_event_timestamp),
            "tweet_count": self.tweet_count,
            "retrieved_at": format_utc(self.retrieved_at),
            "request_id": self.request_id,
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class XCountsDatasetResult:
    dataset_id: str
    rows: tuple[XCountsBucket, ...]
    manifest: Mapping[str, Any]
    counts_path: Path
    manifest_path: Path
    estimate: XCostEstimateReport

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "row_count": len(self.rows),
            "counts_path": str(self.counts_path),
            "manifest_path": str(self.manifest_path),
            "manifest": dict(self.manifest),
            "estimate": self.estimate.as_dict(),
        }


def estimate_x_counts_cost(
    *,
    market: str,
    start: datetime,
    end: datetime,
    budget: XCostBudget | None = None,
    catalog: XQueryCatalog = DEFAULT_X_QUERY_CATALOG,
    categories: Sequence[str] | None = None,
) -> XCostEstimateReport:
    if budget is not None:
        budget.validate()
    start = ensure_utc(start)
    end = ensure_utc(end)
    if start >= end:
        raise XBudgetError("X estimate start time must be before end time")
    lines: list[XCostEstimateLine] = []
    for category in catalog.enabled_categories(categories):
        profile = ENDPOINT_PROFILES[category.endpoint_family]
        chunk_count = len(time_chunks(start, end, max_days=profile.max_days_per_request))
        lines.append(
            XCostEstimateLine(
                category=category.name,
                endpoint_family=category.endpoint_family,
                endpoint_path=profile.path,
                granularity=category.granularity,
                chunk_count=chunk_count,
                request_unit_cost_usd=profile.request_unit_cost_usd,
                estimated_cost_usd=chunk_count * profile.request_unit_cost_usd,
                query_length=len(category.query),
            )
        )
    estimated_cost = sum(line.estimated_cost_usd for line in lines)
    reasons: list[str] = []
    if budget is not None:
        if estimated_cost > budget.daily_cap_usd:
            reasons.append(
                f"estimated cost ${estimated_cost:.4f} exceeds daily cap ${budget.daily_cap_usd:.4f}"
            )
    return XCostEstimateReport(
        schema_version="x_api_counts_cost_estimate.v1",
        market=market,
        start_time=start,
        end_time=end,
        query_catalog_version=catalog.version,
        lines=tuple(lines),
        budget=budget,
        budget_status="rejected" if reasons else "approved",
        rejection_reasons=tuple(reasons),
    )


def collect_x_counts_dataset(
    *,
    market: str,
    start: datetime,
    end: datetime,
    output_root: str | Path,
    budget: XCostBudget | None = None,
    client: XCountsClient,
    catalog: XQueryCatalog = DEFAULT_X_QUERY_CATALOG,
    categories: Sequence[str] | None = None,
    source_mode: Literal["fixture", "x_api_live"] = "fixture",
    retrieved_at: datetime | None = None,
    dataset_id: str | None = None,
    allow_partial: bool = False,
    max_pages_per_window: int = 100,
) -> XCountsDatasetResult:
    start = ensure_utc(start)
    end = ensure_utc(end)
    retrieved = ensure_utc(retrieved_at or datetime.now(tz=UTC))
    estimate = estimate_x_counts_cost(
        market=market,
        start=start,
        end=end,
        budget=budget,
        catalog=catalog,
        categories=categories,
    )
    estimate.assert_approved()
    collected_categories = catalog.enabled_categories(categories)

    output_root = Path(output_root).expanduser()
    ensure_ignored_artifact_root(output_root)
    dataset_id = dataset_id or default_dataset_id(market, catalog.version, start, end)
    dataset_dir = output_root / "external-signals" / "x-counts" / dataset_id
    counts_path = dataset_dir / "counts.jsonl"
    manifest_path = dataset_dir / "manifest.json"
    rows: list[XCountsBucket] = []
    exclusions: list[dict[str, Any]] = []
    actual_request_count = 0
    successful_request_count = 0
    actual_cost_usd = 0.0

    for category in collected_categories:
        profile = ENDPOINT_PROFILES[category.endpoint_family]
        for chunk_index, (chunk_start, chunk_end) in enumerate(
            time_chunks(start, end, max_days=profile.max_days_per_request),
            start=1,
        ):
            next_token: str | None = None
            page = 0
            while True:
                page += 1
                if page > max_pages_per_window:
                    message = f"pagination exceeded {max_pages_per_window} pages"
                    handle_collection_error(
                        allow_partial,
                        exclusions,
                        category=category.name,
                        chunk_start=chunk_start,
                        chunk_end=chunk_end,
                        error=message,
                    )
                    break
                try:
                    payload = client.get_counts(
                        category_name=category.name,
                        endpoint_family=category.endpoint_family,
                        query=category.query,
                        start=chunk_start,
                        end=chunk_end,
                        granularity=category.granularity,
                        next_token=next_token,
                    )
                    actual_request_count += 1
                    if source_mode == "x_api_live":
                        actual_cost_usd += profile.request_unit_cost_usd
                        if budget is not None and actual_cost_usd > budget.daily_cap_usd:
                            raise XBudgetError(
                                f"actual X cost ${actual_cost_usd:.4f} exceeds "
                                f"daily cap ${budget.daily_cap_usd:.4f}"
                            )
                    payload_hash = canonical_payload_hash(payload)
                    request_id = (
                        f"{dataset_id}:{category.name}:{chunk_index}:{page}:"
                        f"{payload_hash[:12]}"
                    )
                    rows.extend(
                        normalize_counts_payload(
                            payload,
                            catalog_version=catalog.version,
                            category=category,
                            retrieved_at=retrieved,
                            request_id=request_id,
                            payload_hash=payload_hash,
                        )
                    )
                    successful_request_count += 1
                    next_token = response_next_token(payload)
                    if not next_token:
                        break
                except Exception as exc:
                    handle_collection_error(
                        allow_partial,
                        exclusions,
                        category=category.name,
                        chunk_start=chunk_start,
                        chunk_end=chunk_end,
                        error=f"{exc.__class__.__name__}: {exc}",
                    )
                    break

    write_jsonl(counts_path, [row.as_dict() for row in rows])
    artifact_hash = file_sha256(counts_path)
    manifest = build_x_counts_manifest(
        dataset_id=dataset_id,
        market=market,
        source_mode=source_mode,
        catalog=catalog,
        collected_categories=collected_categories,
        start=start,
        end=end,
        rows=rows,
        estimate=estimate,
        actual_request_count=actual_request_count,
        successful_request_count=successful_request_count,
        actual_cost_usd=actual_cost_usd,
        counts_path=counts_path,
        counts_sha256=artifact_hash,
        exclusions=exclusions,
    )
    write_json(manifest_path, manifest)
    return XCountsDatasetResult(
        dataset_id=dataset_id,
        rows=tuple(rows),
        manifest=manifest,
        counts_path=counts_path,
        manifest_path=manifest_path,
        estimate=estimate,
    )


def normalize_counts_payload(
    payload: Mapping[str, Any],
    *,
    catalog_version: str,
    category: XQueryCategory,
    retrieved_at: datetime,
    request_id: str,
    payload_hash: str,
) -> list[XCountsBucket]:
    if payload.get("errors"):
        raise XResponseError(f"X counts response contains errors for {category.name}")
    data = payload.get("data", [])
    if data is None:
        data = []
    if not isinstance(data, list):
        raise XResponseError("X counts response data must be a list")
    rows: list[XCountsBucket] = []
    for item in data:
        if not isinstance(item, Mapping):
            raise XResponseError("X counts response rows must be objects")
        try:
            start = parse_utc(item["start"])
            end = parse_utc(item["end"])
            tweet_count = int(item["tweet_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise XResponseError(f"malformed X counts bucket for {category.name}") from exc
        if start >= end:
            raise XResponseError(f"X counts bucket start must be before end for {category.name}")
        if tweet_count < 0:
            raise XResponseError(f"X counts bucket count must not be negative for {category.name}")
        rows.append(
            XCountsBucket(
                source_identity=X_SOURCE_IDENTITY,
                schema_version=X_COUNTS_SCHEMA_VERSION,
                query_catalog_version=catalog_version,
                category=category.name,
                endpoint_family=category.endpoint_family,
                granularity=category.granularity,
                start=start,
                end=end,
                tweet_count=tweet_count,
                retrieved_at=retrieved_at,
                request_id=request_id,
                payload_hash=payload_hash,
            )
        )
    return sorted(rows, key=lambda row: (row.category, row.start, row.end))


def materialize_x_signal_features(
    decision_rows: Sequence[Mapping[str, Any]],
    count_rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    windows_seconds: Sequence[int] = DEFAULT_COUNT_WINDOWS_SECONDS,
) -> list[dict[str, Any]]:
    buckets = [coerce_counts_bucket(row) for row in count_rows]
    categories = sorted({bucket.category for bucket in buckets})
    by_category: dict[str, list[XCountsBucket]] = {
        category: sorted(
            [bucket for bucket in buckets if bucket.category == category],
            key=lambda bucket: bucket.end,
        )
        for category in categories
    }
    output: list[dict[str, Any]] = []
    for row in decision_rows:
        decision = decision_timestamp_from_row(row)
        enriched = dict(row)
        selected_for_any_feature: list[XCountsBucket] = []
        missing_category_count = 0
        for category in categories:
            category_rows = by_category[category]
            day_rows = rows_in_window(category_rows, decision, 86_400)
            if not day_rows:
                missing_category_count += 1
            for window_seconds in windows_seconds:
                selected = rows_in_window(category_rows, decision, window_seconds)
                selected_for_any_feature.extend(selected)
                label = window_label(window_seconds)
                count = sum(bucket.tweet_count for bucket in selected)
                enriched[f"x_counts_{category}_{label}"] = float(count)
                enriched[f"x_attention_{category}_{label}_vs_24h_z"] = rolling_zscore(
                    count,
                    [bucket.tweet_count for bucket in day_rows],
                )
        total_15m = sum(
            float(value)
            for key, value in enriched.items()
            if key.startswith("x_counts_") and key.endswith("_15m")
        )
        enriched["x_total_count_15m"] = total_15m
        enriched["x_signal_missing_category_count"] = float(missing_category_count)
        max_source = max((bucket.source_event_timestamp for bucket in selected_for_any_feature), default=None)
        if max_source is not None and max_source > decision:
            raise XNoLookaheadError(
                "X source event timestamp after decision timestamp: "
                f"{format_utc(max_source)} > {format_utc(decision)}"
            )
        max_retrieved = max((bucket.retrieved_at for bucket in selected_for_any_feature), default=None)
        enriched["x_signal_manifest_id"] = str(manifest.get("dataset_id", ""))
        enriched["x_signal_query_catalog_version"] = str(manifest.get("query_catalog_version", ""))
        enriched["x_signal_max_source_event_timestamp_utc"] = (
            format_utc(max_source) if max_source else ""
        )
        enriched["x_signal_retrieved_at_utc"] = format_utc(max_retrieved) if max_retrieved else ""
        output.append(enriched)
    validate_x_signal_feature_rows(output)
    return output


def generate_minimal_x_features(
    decision_rows: Sequence[Mapping[str, Any]],
    count_rows: Sequence[Mapping[str, Any]],
    *,
    windows_seconds: Sequence[int] = (300, 900, 3600),
) -> list[dict[str, Any]]:
    """Fast X count feature join: trailing counts only, no manifest required."""

    indexes = build_count_prefix_indexes(count_rows)
    output: list[dict[str, Any]] = []
    for row in decision_rows:
        decision = decision_timestamp_from_row(row)
        enriched = dict(row)
        for window_seconds in windows_seconds:
            label = window_label(window_seconds)
            total = 0
            for category, index in indexes.items():
                count = prefix_count(index, decision, window_seconds)
                enriched[f"x_counts_{category}_{label}"] = float(count)
                total += count
            enriched[f"x_total_count_{label}"] = float(total)
        output.append(enriched)
    return output


def build_count_prefix_indexes(
    count_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, list[Any]]]:
    buckets = [coerce_counts_bucket(row) for row in count_rows]
    categories = sorted({bucket.category for bucket in buckets})
    indexes: dict[str, dict[str, list[Any]]] = {}
    for category in categories:
        category_rows = sorted(
            [bucket for bucket in buckets if bucket.category == category],
            key=lambda bucket: bucket.source_event_timestamp,
        )
        times = [bucket.source_event_timestamp for bucket in category_rows]
        prefix = [0]
        for bucket in category_rows:
            prefix.append(prefix[-1] + bucket.tweet_count)
        indexes[category] = {"times": times, "prefix": prefix}
    return indexes


def prefix_count(index: Mapping[str, list[Any]], decision: datetime, window_seconds: int) -> int:
    times = index["times"]
    prefix = index["prefix"]
    start = decision - timedelta(seconds=window_seconds)
    right = bisect_right(times, decision)
    left = bisect_right(times, start)
    return int(prefix[right] - prefix[left])


def validate_x_signal_feature_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        decision = decision_timestamp_from_row(row)
        max_source = row.get("x_signal_max_source_event_timestamp_utc")
        if max_source in (None, ""):
            continue
        source = parse_utc(max_source)
        if source > decision:
            raise XNoLookaheadError(
                "X feature row has source timestamp after decision timestamp: "
                f"{format_utc(source)} > {format_utc(decision)}"
            )


def planned_x_feature_names(
    categories: Sequence[XQueryCategory],
    *,
    windows_seconds: Sequence[int] = DEFAULT_COUNT_WINDOWS_SECONDS,
) -> list[str]:
    names: list[str] = []
    for category in categories:
        if not category.enabled:
            continue
        for window_seconds in windows_seconds:
            label = window_label(window_seconds)
            names.append(f"x_counts_{category.name}_{label}")
            names.append(f"x_attention_{category.name}_{label}_vs_24h_z")
    names.append("x_total_count_15m")
    names.append("x_signal_missing_category_count")
    return names


def build_x_counts_manifest(
    *,
    dataset_id: str,
    market: str,
    source_mode: str,
    catalog: XQueryCatalog,
    collected_categories: Sequence[XQueryCategory],
    start: datetime,
    end: datetime,
    rows: Sequence[XCountsBucket],
    estimate: XCostEstimateReport,
    actual_request_count: int,
    successful_request_count: int,
    actual_cost_usd: float,
    counts_path: Path,
    counts_sha256: str,
    exclusions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    coverage = coverage_summary(rows, collected_categories)
    suitability = "suitable_for_model_evaluation"
    if exclusions or not rows:
        suitability = "inconclusive"
    return {
        "schema_version": X_MANIFEST_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "source_identity": X_SOURCE_IDENTITY,
        "source_mode": source_mode,
        "market": market,
            "query_catalog_version": catalog.version,
            "query_categories": [
            category.as_dict(include_query=False) for category in collected_categories
        ],
        "tested_time_range": {
            "start": format_utc(start),
            "end": format_utc(end),
        },
        "coverage": coverage,
        "feature_names": planned_x_feature_names(collected_categories),
        "exclusion_reasons": [dict(exclusion) for exclusion in exclusions],
        "estimated_cost": {
            "request_count": estimate.estimated_request_count,
            "cost_usd": round(estimate.estimated_cost_usd, 6),
            "budget_status": estimate.budget_status,
            "budget": estimate.budget.as_dict() if estimate.budget is not None else None,
        },
        "actual_cost": {
            "request_count": actual_request_count,
            "successful_request_count": successful_request_count,
            "cost_usd": round(actual_cost_usd, 6),
        },
        "artifact_hashes": {
            "counts_jsonl_sha256": counts_sha256,
        },
        "artifact_locations": {
            "counts_jsonl": str(counts_path),
        },
        "suitability": suitability,
        "no_lookahead_basis": (
            "source_event_timestamp is the count bucket end timestamp; feature rows may only "
            "use buckets whose source_event_timestamp is at or before the decision timestamp. "
            "retrieved_at is retained for provenance and does not make historical source events "
            "unobservable during intentional offline backfills."
        ),
        "non_promotion_notice": (
            "External signal research datasets inform model evaluation only and do not authorize "
            "Model registry promotion, live trading, or Current MVP changes."
        ),
    }


def coverage_summary(
    rows: Sequence[XCountsBucket],
    categories: Sequence[XQueryCategory],
) -> dict[str, Any]:
    by_category: dict[str, list[XCountsBucket]] = {
        category.name: sorted(
            [row for row in rows if row.category == category.name],
            key=lambda row: row.source_event_timestamp,
        )
        for category in categories
    }
    return {
        "row_count": len(rows),
        "category_count": len(categories),
        "categories": {
            category: {
                "bucket_count": len(category_rows),
                "total_tweet_count": sum(row.tweet_count for row in category_rows),
                "first_source_event_timestamp": format_utc(category_rows[0].source_event_timestamp)
                if category_rows
                else None,
                "last_source_event_timestamp": format_utc(category_rows[-1].source_event_timestamp)
                if category_rows
                else None,
            }
            for category, category_rows in by_category.items()
        },
    }


def load_x_query_catalog(path: str | Path | None) -> XQueryCatalog:
    if path is None:
        return DEFAULT_X_QUERY_CATALOG
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise XQueryCatalogError("X query catalog file must contain a JSON object")
    return XQueryCatalog.from_mapping(payload)


def load_x_counts_rows(path: str | Path) -> list[dict[str, Any]]:
    return load_jsonl(Path(path))


def load_x_manifest(path: str | Path) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise XResponseError("X manifest must contain a JSON object")
    return payload


def handle_collection_error(
    allow_partial: bool,
    exclusions: list[dict[str, Any]],
    *,
    category: str,
    chunk_start: datetime,
    chunk_end: datetime,
    error: str,
) -> None:
    if not allow_partial:
        raise XResponseError(error)
    exclusions.append(
        {
            "category": category,
            "start": format_utc(chunk_start),
            "end": format_utc(chunk_end),
            "reason": error,
        }
    )


def coerce_counts_bucket(row: Mapping[str, Any]) -> XCountsBucket:
    return XCountsBucket(
        source_identity=str(row.get("source_identity", X_SOURCE_IDENTITY)),
        schema_version=str(row.get("schema_version", X_COUNTS_SCHEMA_VERSION)),
        query_catalog_version=str(row.get("query_catalog_version", "")),
        category=str(row["category"]),
        endpoint_family=str(row.get("endpoint_family", "counts_all")),  # type: ignore[arg-type]
        granularity=str(row.get("granularity", "minute")),  # type: ignore[arg-type]
        start=parse_utc(row["start"]),
        end=parse_utc(row["end"]),
        tweet_count=int(row["tweet_count"]),
        retrieved_at=parse_utc(row.get("retrieved_at") or row.get("source_retrieved_at")),
        request_id=str(row.get("request_id", "")),
        payload_hash=str(row.get("payload_hash", "")),
    )


def rows_in_window(
    rows: Sequence[XCountsBucket],
    decision: datetime,
    window_seconds: int,
) -> list[XCountsBucket]:
    earliest = decision - timedelta(seconds=window_seconds)
    return [
        row for row in rows
        if row.source_event_timestamp <= decision and row.source_event_timestamp > earliest
    ]


def rolling_zscore(value: int | float, history: Sequence[int | float]) -> float:
    if len(history) < 2:
        return 0.0
    mean = sum(float(item) for item in history) / len(history)
    variance = sum((float(item) - mean) ** 2 for item in history) / (len(history) - 1)
    std = math.sqrt(variance)
    if std <= 0:
        return 0.0
    return (float(value) - mean) / std


def time_chunks(start: datetime, end: datetime, *, max_days: int) -> list[tuple[datetime, datetime]]:
    if start >= end:
        raise XSignalError("time chunk start must be before end")
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    delta = timedelta(days=max_days)
    while cursor < end:
        chunk_end = min(end, cursor + delta)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return chunks


def response_next_token(payload: Mapping[str, Any]) -> str | None:
    meta = payload.get("meta")
    if not isinstance(meta, Mapping):
        return None
    token = meta.get("next_token")
    return str(token) if token else None


def generate_fixture_counts_payload(
    category_name: str,
    *,
    start: datetime,
    end: datetime,
    granularity: Granularity,
) -> dict[str, Any]:
    step = {"minute": 60, "hour": 3600, "day": 86_400}[granularity]
    rows: list[dict[str, Any]] = []
    cursor = start
    base_count = (sum(ord(char) for char in category_name) % 7) + 1
    index = 0
    while cursor < end:
        bucket_end = min(end, cursor + timedelta(seconds=step))
        rows.append(
            {
                "start": format_utc(cursor),
                "end": format_utc(bucket_end),
                "tweet_count": base_count + (index % 3),
            }
        )
        cursor = bucket_end
        index += 1
    return {"data": rows, "meta": {"total_tweet_count": sum(row["tweet_count"] for row in rows)}}


def ensure_ignored_artifact_root(path: Path) -> None:
    if not any(part in IGNORED_ARTIFACT_ROOT_NAMES for part in path.parts):
        raise XArtifactLocationError(
            "X generated artifacts must be written under an ignored/private root "
            "such as artifacts/, data/, or research/"
        )


def default_dataset_id(market: str, catalog_version: str, start: datetime, end: datetime) -> str:
    token = canonical_payload_hash(
        {
            "market": market,
            "catalog_version": catalog_version,
            "start": format_utc(start),
            "end": format_utc(end),
        }
    )[:12]
    safe_market = re.sub(r"[^a-z0-9]+", "_", market.lower()).strip("_")
    return f"x_counts_{safe_market}_{token}"


def decision_timestamp_from_row(row: Mapping[str, Any]) -> datetime:
    value = row.get("decision_timestamp") or row.get("decision_timestamp_utc")
    if value in (None, ""):
        raise XNoLookaheadError("decision row is missing decision_timestamp")
    return parse_utc(value)


def window_label(seconds: int) -> str:
    if seconds % 86_400 == 0:
        return f"{seconds // 86_400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if value in (None, ""):
        raise ValueError("timestamp value is required")
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return ensure_utc(parsed)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_utc(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def canonical_payload_hash(payload: Any) -> str:
    import hashlib

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, Mapping):
            raise XResponseError(f"JSONL row {line_number} must be an object: {path}")
        output.append(dict(payload))
    return output
