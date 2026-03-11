import type { MarketSummary, ProviderId } from "@alphadb/market-core";

import { formatCompactMoney, formatEndDate, formatPrice, providerThemes } from "../shared";

function formatSignedPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "--";
  }

  const percent = value * 100;
  const prefix = percent > 0 ? "+" : "";
  return `${prefix}${percent.toFixed(Math.abs(percent) >= 10 ? 1 : 2)}%`;
}

export function MarketDetail({
  provider,
  market,
  liveStatus,
  saved,
}: {
  provider: ProviderId;
  market: MarketSummary | null;
  liveStatus: string;
  saved: boolean;
}) {
  if (!market) {
    return (
      <section className="panel">
        <div className="panel-title">Market Detail</div>
        <div className="detail-card">No market selected.</div>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div className="panel-title">Market Detail</div>
        <div className="panel-meta">{providerThemes[provider].label}</div>
      </div>
      <div className="detail-card">
        <div className="detail-title">{market.question}</div>
        <div className="detail-subtitle">{market.eventTitle ?? market.seriesTitle ?? "Market detail unavailable"}</div>
        <div
          className={`detail-change ${
            market.oneDayPriceChange === null
              ? "neutral"
              : market.oneDayPriceChange > 0
                ? "positive"
                : market.oneDayPriceChange < 0
                  ? "negative"
                  : "neutral"
          }`}
        >
          Change 24h {formatSignedPercent(market.oneDayPriceChange)}
        </div>
        <div className="detail-grid">
          <span>Ends {formatEndDate(market.endDate)}</span>
          <span>Vol24 {formatCompactMoney(market.volume24hr)}</span>
          <span>Liquidity {formatCompactMoney(market.liquidity)}</span>
          <span>Bid {formatPrice(market.bestBid)}</span>
          <span>Ask {formatPrice(market.bestAsk)}</span>
          <span>Last {formatPrice(market.lastTradePrice)}</span>
          <span>Symbol {market.symbol}</span>
          <span>{providerThemes[provider].label} feed</span>
          <span>Saved {saved ? "yes" : "no"}</span>
        </div>
        <div className="live-line">{liveStatus}</div>
      </div>
    </section>
  );
}
