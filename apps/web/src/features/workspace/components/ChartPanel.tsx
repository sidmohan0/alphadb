import { useEffect, useRef } from "react";
import {
  AreaSeries,
  ColorType,
  createChart,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PricePoint, ProviderId } from "@alphadb/market-core";

import { NEGATIVE_ACCENT, providerThemes } from "../shared";

function normalizeSeriesData(points: PricePoint[]): Array<{ time: UTCTimestamp; value: number }> {
  const sortedPoints = [...points].sort((left, right) => left.timestamp - right.timestamp);
  const normalized: Array<{ time: UTCTimestamp; value: number }> = [];

  for (const point of sortedPoints) {
    if (!Number.isFinite(point.timestamp) || !Number.isFinite(point.price)) {
      continue;
    }

    const entry = {
      time: Math.floor(point.timestamp / 1000) as UTCTimestamp,
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

function summarizeSeries(points: PricePoint[]) {
  const normalized = normalizeSeriesData(points);
  const first = normalized[0]?.value ?? null;
  const last = normalized.at(-1)?.value ?? null;
  const high = normalized.length > 0 ? Math.max(...normalized.map((point) => point.value)) : null;
  const low = normalized.length > 0 ? Math.min(...normalized.map((point) => point.value)) : null;
  const change = first !== null && last !== null ? last - first : null;
  const rising = change === null ? true : change >= 0;

  return {
    normalized,
    first,
    last,
    high,
    low,
    change,
    rising,
  };
}

function buildBandPrices(high: number | null, low: number | null): number[] {
  if (high === null || low === null || !Number.isFinite(high) || !Number.isFinite(low) || high === low) {
    return [];
  }

  const range = high - low;
  return [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => Number((low + range * ratio).toFixed(4)));
}

function formatChartPrice(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "--";
  }

  return `${value.toFixed(value >= 10 ? 1 : 2)}c`;
}

function useChart(provider: ProviderId, points: PricePoint[], loading: boolean): React.RefObject<HTMLDivElement> {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

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
      priceLineVisible: false,
      crosshairMarkerBorderColor: theme.border,
      crosshairMarkerBackgroundColor: theme.chartLine,
    }) as ISeriesApi<"Area">;

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
      for (const line of priceLinesRef.current) {
        seriesRef.current?.removePriceLine(line);
      }
      priceLinesRef.current = [];
      seriesRef.current = null;
      chartRef.current?.remove();
      chartRef.current = null;
    };
  }, [provider]);

  useEffect(() => {
    if (!seriesRef.current) {
      return;
    }

    const summary = summarizeSeries(points);
    const theme = providerThemes[provider];
    const series = seriesRef.current;

    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];

    series.applyOptions({
      lineColor: summary.rising ? theme.chartLine : NEGATIVE_ACCENT,
      topColor: summary.rising ? theme.chartFillTop : "rgba(204, 0, 0, 0.18)",
      bottomColor: summary.rising ? theme.chartFillBottom : "rgba(32, 0, 0, 0.04)",
      crosshairMarkerBackgroundColor: summary.rising ? theme.chartLine : NEGATIVE_ACCENT,
    });

    const bandColor = summary.rising ? theme.border : "#4d1818";
    for (const price of buildBandPrices(summary.high, summary.low)) {
      const line = series.createPriceLine({
        price,
        color: bandColor,
        lineWidth: 1,
        lineStyle: LineStyle.SparseDotted,
        lineVisible: true,
        axisLabelVisible: false,
        title: "",
      });
      priceLinesRef.current.push(line);
    }

    if (summary.last !== null) {
      const lastLine = series.createPriceLine({
        price: summary.last,
        color: summary.rising ? theme.chartLine : NEGATIVE_ACCENT,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        lineVisible: true,
        axisLabelVisible: true,
        axisLabelTextColor: "#f5f2e8",
        axisLabelColor: summary.rising ? theme.chartLine : NEGATIVE_ACCENT,
        title: "LAST",
      });
      priceLinesRef.current.push(lastLine);
    }

    series.setData(summary.normalized);
    chartRef.current?.timeScale().fitContent();
  }, [points, provider]);

  useEffect(() => {
    if (loading && seriesRef.current) {
      seriesRef.current.setData([]);
    }
  }, [loading]);

  return containerRef;
}

export function ChartPanel({
  provider,
  points,
  loading,
}: {
  provider: ProviderId;
  points: PricePoint[];
  loading: boolean;
}) {
  const containerRef = useChart(provider, points, loading);
  const summary = summarizeSeries(points);
  const chartChange = summary.change;
  const changeLabel =
    chartChange === null ? `${points.length} pts` : `${chartChange > 0 ? "+" : ""}${chartChange.toFixed(2)}c`;

  return (
    <section className="panel">
      <div className="panel-header">
        <div className="panel-title">Chart</div>
        <div className={`panel-meta ${chartChange === null ? "" : chartChange < 0 ? "negative" : chartChange > 0 ? "positive" : "neutral"}`}>
          {loading ? "syncing" : changeLabel}
        </div>
      </div>
      <div className="chart-shell">
        <div ref={containerRef} className="chart-canvas" />
        {!loading && points.length === 0 ? (
          <div className="chart-empty">No chart data available for this selection.</div>
        ) : null}
        {loading ? <div className="chart-empty">Loading chart…</div> : null}
      </div>
      <div className="chart-stats">
        <span>O {formatChartPrice(summary.first)}</span>
        <span>H {formatChartPrice(summary.high)}</span>
        <span>L {formatChartPrice(summary.low)}</span>
        <span className={chartChange === null ? "neutral" : chartChange < 0 ? "negative" : chartChange > 0 ? "positive" : "neutral"}>
          C {formatChartPrice(summary.last)}
        </span>
      </div>
    </section>
  );
}
