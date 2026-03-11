import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { formatCompactMoney, formatEndDate, formatPrice, providerThemes } from "../shared";
function formatSignedPercent(value) {
    if (value === null || !Number.isFinite(value)) {
        return "--";
    }
    const percent = value * 100;
    const prefix = percent > 0 ? "+" : "";
    return `${prefix}${percent.toFixed(Math.abs(percent) >= 10 ? 1 : 2)}%`;
}
export function MarketDetail({ provider, market, liveStatus, saved, }) {
    if (!market) {
        return (_jsxs("section", { className: "panel", children: [_jsx("div", { className: "panel-title", children: "Market Detail" }), _jsx("div", { className: "detail-card", children: "No market selected." })] }));
    }
    return (_jsxs("section", { className: "panel", children: [_jsxs("div", { className: "panel-header", children: [_jsx("div", { className: "panel-title", children: "Market Detail" }), _jsx("div", { className: "panel-meta", children: providerThemes[provider].label })] }), _jsxs("div", { className: "detail-card", children: [_jsx("div", { className: "detail-title", children: market.question }), _jsx("div", { className: "detail-subtitle", children: market.eventTitle ?? market.seriesTitle ?? "Market detail unavailable" }), _jsxs("div", { className: `detail-change ${market.oneDayPriceChange === null
                            ? "neutral"
                            : market.oneDayPriceChange > 0
                                ? "positive"
                                : market.oneDayPriceChange < 0
                                    ? "negative"
                                    : "neutral"}`, children: ["Change 24h ", formatSignedPercent(market.oneDayPriceChange)] }), _jsxs("div", { className: "detail-grid", children: [_jsxs("span", { children: ["Ends ", formatEndDate(market.endDate)] }), _jsxs("span", { children: ["Vol24 ", formatCompactMoney(market.volume24hr)] }), _jsxs("span", { children: ["Liquidity ", formatCompactMoney(market.liquidity)] }), _jsxs("span", { children: ["Bid ", formatPrice(market.bestBid)] }), _jsxs("span", { children: ["Ask ", formatPrice(market.bestAsk)] }), _jsxs("span", { children: ["Last ", formatPrice(market.lastTradePrice)] }), _jsxs("span", { children: ["Symbol ", market.symbol] }), _jsxs("span", { children: [providerThemes[provider].label, " feed"] }), _jsxs("span", { children: ["Saved ", saved ? "yes" : "no"] })] }), _jsx("div", { className: "live-line", children: liveStatus })] })] }));
}
