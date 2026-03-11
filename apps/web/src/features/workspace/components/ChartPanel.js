import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart, LineStyle } from "lightweight-charts";
import { NEGATIVE_ACCENT, providerThemes } from "../shared";
function normalizeSeriesData(points) {
    const sortedPoints = [...points].sort((left, right) => left.timestamp - right.timestamp);
    const normalized = [];
    for (const point of sortedPoints) {
        if (!Number.isFinite(point.timestamp) || !Number.isFinite(point.price)) {
            continue;
        }
        const entry = {
            time: Math.floor(point.timestamp / 1000),
            value: Number((point.price * 100).toFixed(4)),
        };
        const previous = normalized.at(-1);
        if (previous && previous.time === entry.time) {
            normalized[normalized.length - 1] = entry;
            continue;
        }
        normalized.push(entry);
    }
    return normalized;
}
function useChart(provider, points, loading) {
    const containerRef = useRef(null);
    const chartRef = useRef(null);
    const seriesRef = useRef(null);
    useEffect(() => {
        const container = containerRef.current;
        if (!container) {
            return;
        }
        const theme = providerThemes[provider];
        const chart = createChart(container, {
            autoSize: true,
            layout: {
                background: { type: ColorType.Solid, color: theme.panel },
                textColor: theme.text,
                fontFamily: '"Space Mono", monospace',
            },
            grid: {
                vertLines: { color: theme.borderSoft, style: LineStyle.Dotted },
                horzLines: { color: theme.border, style: LineStyle.Dotted },
            },
            rightPriceScale: {
                borderColor: theme.borderSoft,
            },
            timeScale: {
                borderColor: theme.borderSoft,
                timeVisible: true,
            },
            crosshair: {
                vertLine: { color: theme.border, style: LineStyle.Solid, width: 1 },
                horzLine: { color: theme.border, style: LineStyle.Dotted, width: 1 },
            },
        });
        const series = chart.addSeries(AreaSeries, {
            lineColor: theme.chartLine,
            topColor: theme.chartFillTop,
            bottomColor: theme.chartFillBottom,
            lineWidth: 2,
            priceLineVisible: true,
            crosshairMarkerBorderColor: theme.border,
            crosshairMarkerBackgroundColor: theme.chartLine,
        });
        chartRef.current = chart;
        seriesRef.current = series;
        const resizeObserver = new ResizeObserver(() => {
            const width = container.clientWidth;
            const height = container.clientHeight;
            if (width > 0 && height > 0) {
                chart.applyOptions({ width, height });
                chart.timeScale().fitContent();
            }
        });
        resizeObserver.observe(container);
        return () => {
            resizeObserver.disconnect();
            seriesRef.current = null;
            chartRef.current?.remove();
            chartRef.current = null;
        };
    }, [provider]);
    useEffect(() => {
        if (!seriesRef.current) {
            return;
        }
        const data = normalizeSeriesData(points);
        const first = data[0]?.value ?? null;
        const last = data.at(-1)?.value ?? null;
        const rising = first !== null && last !== null ? last >= first : true;
        const theme = providerThemes[provider];
        seriesRef.current.applyOptions({
            lineColor: rising ? theme.chartLine : NEGATIVE_ACCENT,
            topColor: rising ? theme.chartFillTop : "rgba(204, 0, 0, 0.18)",
            bottomColor: rising ? theme.chartFillBottom : "rgba(32, 0, 0, 0.04)",
            crosshairMarkerBackgroundColor: rising ? theme.chartLine : NEGATIVE_ACCENT,
        });
        seriesRef.current.setData(data);
        chartRef.current?.timeScale().fitContent();
    }, [points, provider]);
    useEffect(() => {
        if (loading && seriesRef.current) {
            seriesRef.current.setData([]);
        }
    }, [loading]);
    return containerRef;
}
export function ChartPanel({ provider, points, loading, }) {
    const containerRef = useChart(provider, points, loading);
    const normalized = normalizeSeriesData(points);
    const first = normalized[0]?.value ?? null;
    const last = normalized.at(-1)?.value ?? null;
    const chartChange = first !== null && last !== null ? last - first : null;
    const changeLabel = chartChange === null ? `${points.length} pts` : `${chartChange > 0 ? "+" : ""}${chartChange.toFixed(2)}c`;
    return (_jsxs("section", { className: "panel", children: [_jsxs("div", { className: "panel-header", children: [_jsx("div", { className: "panel-title", children: "Chart" }), _jsx("div", { className: `panel-meta ${chartChange === null ? "" : chartChange < 0 ? "negative" : chartChange > 0 ? "positive" : "neutral"}`, children: loading ? "syncing" : changeLabel })] }), _jsxs("div", { className: "chart-shell", children: [_jsx("div", { ref: containerRef, className: "chart-canvas" }), !loading && points.length === 0 ? (_jsx("div", { className: "chart-empty", children: "No chart data available for this selection." })) : null, loading ? _jsx("div", { className: "chart-empty", children: "Loading chart\u2026" }) : null] })] }));
}
