import type { MarketSummary, ProviderId } from "@alphadb/market-core";

import { formatCompactMoney, formatEndDate, formatPrice, providerThemes } from "../shared";

function toneClass(change: number | null): string {
  if (change === null || !Number.isFinite(change)) {
    return "neutral";
  }

  if (change > 0) {
    return "positive";
  }

  if (change < 0) {
    return "negative";
  }

  return "neutral";
}

export function MarketTable({
  provider,
  markets,
  selectedIndex,
  focused,
  savedIds,
  recentIds,
  onSelect,
}: {
  provider: ProviderId;
  markets: MarketSummary[];
  selectedIndex: number;
  focused: boolean;
  savedIds: Set<string>;
  recentIds: Set<string>;
  onSelect: (index: number) => void;
}) {
  const theme = providerThemes[provider];

  return (
    <section className="panel">
      <div className="panel-header">
        <div className={`panel-title provider-title ${focused ? "focused" : ""}`}>{theme.label}{focused ? " focus" : ""}</div>
        <div className="panel-meta">{markets.length} mkts</div>
      </div>
      <div className="market-table-head">
        <span>Question</span>
        <span>Flg</span>
        <span>Px</span>
        <span>Vol24</span>
        <span>End</span>
      </div>
      <div className="market-table-rows">
        {markets.length === 0 ? (
          <div className="market-empty">No markets in this view.</div>
        ) : null}
        {markets.map((market, index) => {
          const flags = `${savedIds.has(market.id) ? "S" : "."}${recentIds.has(market.id) ? "R" : "."}`;
          const priceTone = toneClass(market.oneDayPriceChange);
          return (
            <button
              type="button"
              key={market.id}
              className={`market-row ${index === selectedIndex ? "selected" : ""}`}
              onClick={() => onSelect(index)}
            >
              <span className="market-question">{market.question}</span>
              <span className="market-flag">{flags}</span>
              <span className={`market-number ${priceTone}`}>{formatPrice(market.lastTradePrice ?? market.outcomes[0]?.price ?? null)}</span>
              <span className="market-number neutral">{formatCompactMoney(market.volume24hr)}</span>
              <span className="market-end">{formatEndDate(market.endDate)}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
