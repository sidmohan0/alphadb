"""Registry for tradable market-family specifications."""

from __future__ import annotations

from dataclasses import dataclass, field

from alphadb.markets.spec import MarketSpec, kxbtc15m_spec


@dataclass
class MarketRegistry:
    _specs: dict[str, MarketSpec] = field(default_factory=dict)

    def register(self, spec: MarketSpec) -> None:
        if spec.series in self._specs:
            raise ValueError(f"market spec already registered: {spec.series}")
        self._specs[spec.series] = spec

    def get(self, series: str) -> MarketSpec:
        try:
            return self._specs[series]
        except KeyError as exc:
            raise KeyError(f"unknown market spec: {series}") from exc

    def list(self) -> list[MarketSpec]:
        return [self._specs[key] for key in sorted(self._specs)]


def default_market_registry() -> MarketRegistry:
    registry = MarketRegistry()
    registry.register(kxbtc15m_spec())
    return registry
