import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function ChannelsTable({ model, phase, onPrevious, onNext, }) {
    if (!model) {
        return (_jsxs("section", { className: "card", children: [_jsx("h3", { children: "Discovered channels" }), _jsx("p", { children: "No run data loaded yet." })] }));
    }
    const { channels } = model;
    const isScanning = phase === "submitting" || phase === "polling";
    return (_jsxs("section", { className: "card", children: [_jsx("h3", { children: "Discovered channels" }), _jsx("p", { children: channels.page.total === 0
                    ? "No channels discovered yet for the current scan window."
                    : `Showing ${channels.page.offset + 1} - ${channels.page.offset + channels.items.length} of ${channels.page.total}` }), _jsx("div", { className: "channels-shell", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Asset" }), _jsx("th", { children: "Condition" }), _jsx("th", { children: "Question" }), _jsx("th", { children: "Outcome" }), _jsx("th", { children: "Slug" })] }) }), _jsx("tbody", { children: channels.items.length === 0 ? (_jsx("tr", { children: _jsx("td", { colSpan: 5, children: isScanning
                                        ? "Discovery is still running. No channels found for this page yet."
                                        : "No channels found for this page." }) })) : (channels.items.map((row) => (_jsxs("tr", { children: [_jsx("td", { children: row.assetId }), _jsx("td", { children: row.conditionId || "-" }), _jsx("td", { children: row.question || "-" }), _jsx("td", { children: row.outcome || "-" }), _jsx("td", { children: row.marketSlug || "-" })] }, row.assetId)))) })] }) }), _jsxs("div", { className: "pagination", children: [_jsx("button", { type: "button", onClick: onPrevious, disabled: !onPrevious || channels.page.offset === 0, children: "Previous" }), _jsx("button", { type: "button", onClick: onNext, disabled: !onNext || !channels.page.hasMore, children: "Next" })] })] }));
}
