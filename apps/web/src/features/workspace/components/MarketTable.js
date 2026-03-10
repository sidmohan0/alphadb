import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { formatCompactMoney, formatEndDate, formatPrice, providerThemes } from "../shared";
export function MarketTable({ provider, markets, selectedIndex, focused, savedIds, recentIds, onSelect, }) {
    const theme = providerThemes[provider];
    return (_jsxs("section", { className: "panel", children: [_jsxs("div", { className: `panel-title provider-title ${focused ? "focused" : ""}`, children: [theme.label, focused ? " • focus" : ""] }), _jsxs("div", { className: "market-table-head", children: [_jsx("span", { children: "Question" }), _jsx("span", { children: "Flg" }), _jsx("span", { children: "Px" }), _jsx("span", { children: "Vol24" }), _jsx("span", { children: "End" })] }), _jsxs("div", { className: "market-table-rows", children: [markets.length === 0 ? (_jsx("div", { className: "market-empty", children: "No markets in this view." })) : null, markets.map((market, index) => {
                        const flags = `${savedIds.has(market.id) ? "S" : "."}${recentIds.has(market.id) ? "R" : "."}`;
                        return (_jsxs("button", { type: "button", className: `market-row ${index === selectedIndex ? "selected" : ""}`, onClick: () => onSelect(index), children: [_jsx("span", { className: "market-question", children: market.question }), _jsx("span", { children: flags }), _jsx("span", { children: formatPrice(market.lastTradePrice ?? market.outcomes[0]?.price ?? null) }), _jsx("span", { children: formatCompactMoney(market.volume24hr) }), _jsx("span", { children: formatEndDate(market.endDate) })] }, market.id));
                    })] })] }));
}
