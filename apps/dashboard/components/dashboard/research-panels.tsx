'use client'

import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { StatusBadge } from '@/components/ui/status-badge'
import { AlertTriangle, ExternalLink } from 'lucide-react'
import type { Backtest, MarketInstance, PositionsSummary, ResearchCandidate } from '@/lib/mock-data'

interface ResearchPanelProps {
  className?: string
}

interface ResearchCandidatePanelProps extends ResearchPanelProps {
  data: ResearchCandidate
}

export function ResearchCandidatePanel({ className, data }: ResearchCandidatePanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Research Candidate
        </h3>
        <StatusBadge variant="pending" size="sm">{data.status}</StatusBadge>
      </div>

      <div className="rounded border border-warning/30 bg-warning/5 p-2.5">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium text-foreground">{data.title}</p>
            <p className="text-[10px] leading-relaxed text-muted-foreground">{data.description}</p>
            <div className="flex items-center gap-2 pt-1">
              <Badge variant="secondary" className="h-4 rounded px-1.5 text-[9px]">
                branch: {data.branch}
              </Badge>
              <button className="flex items-center gap-1 text-[9px] text-muted-foreground hover:text-foreground">
                <ExternalLink className="h-2.5 w-2.5" />
                View report
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

interface BacktestSummaryPanelProps extends ResearchPanelProps {
  data: Backtest[]
}

export function BacktestSummaryPanel({ className, data }: BacktestSummaryPanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Backtest Summary
        </h3>
        <button className="text-[9px] text-muted-foreground hover:text-foreground">Run new</button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="pb-1.5 font-medium">Test</th>
              <th className="pb-1.5 font-medium text-right">Runs</th>
              <th className="pb-1.5 font-medium text-right">PnL</th>
              <th className="pb-1.5 font-medium text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.map((test) => (
              <tr key={test.name} className="border-b border-border/50">
                <td className="py-1.5">{test.name}</td>
                <td className="py-1.5 text-right font-mono text-muted-foreground">{test.runs}</td>
                <td
                  className={`py-1.5 text-right font-mono ${
                    test.pnl.startsWith('+') ? 'text-success' : 'text-muted-foreground'
                  }`}
                >
                  {test.pnl}
                </td>
                <td className="py-1.5 text-right">
                  <StatusBadge
                    variant={
                      test.status === 'pass' ? 'ok' : test.status === 'fail' ? 'error' : 'pending'
                    }
                    size="sm"
                  >
                    {test.status}
                  </StatusBadge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface MarketInstancesPanelProps extends ResearchPanelProps {
  data: MarketInstance[]
}

const instanceStatusColors = {
  traded: 'text-success',
  skipped: 'text-warning',
  ignored: 'text-muted-foreground',
}

export function MarketInstancesPanel({ className, data }: MarketInstancesPanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Market Instances
        </h3>
        <StatusBadge variant="inactive" size="sm">{data.length} scanned</StatusBadge>
      </div>

      <ScrollArea className="h-[100px]">
        <div className="space-y-1">
          {data.map((inst) => (
            <div
              key={inst.ticker}
              className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5 text-[10px]"
            >
              <span className="font-mono text-muted-foreground">{inst.ticker}</span>
              <div className="flex items-center gap-2">
                <span className={instanceStatusColors[inst.status]}>{inst.status}</span>
                <span className="font-mono text-muted-foreground">{inst.action}</span>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}

interface PositionsSummaryPanelProps extends ResearchPanelProps {
  data: PositionsSummary
}

export function PositionsSummaryPanel({ className, data }: PositionsSummaryPanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Positions & PnL
        </h3>
        <StatusBadge variant="live" size="sm">live</StatusBadge>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded bg-secondary/50 p-2">
          <div className="text-[9px] uppercase tracking-wide text-muted-foreground">
            Open Exposure
          </div>
          <div className="mt-1 font-mono text-lg font-semibold text-foreground">
            {data.openExposure}
          </div>
        </div>
        <div className="rounded bg-secondary/50 p-2">
          <div className="text-[9px] uppercase tracking-wide text-muted-foreground">
            Realized PnL
          </div>
          <div
            className={`mt-1 font-mono text-lg font-semibold ${
              data.realizedPnl.startsWith('+') ? 'text-success' : 'text-foreground'
            }`}
          >
            {data.realizedPnl}
          </div>
        </div>
        <div className="rounded bg-secondary/50 p-2">
          <div className="text-[9px] uppercase tracking-wide text-muted-foreground">Unsettled</div>
          <div className="mt-1 font-mono text-lg font-semibold text-foreground">{data.unsettled}</div>
        </div>
        <div className="rounded bg-secondary/50 p-2">
          <div className="text-[9px] uppercase tracking-wide text-muted-foreground">Today PnL</div>
          <div
            className={`mt-1 font-mono text-lg font-semibold ${
              data.todayPnl.startsWith('+') ? 'text-success' : 'text-foreground'
            }`}
          >
            {data.todayPnl}
          </div>
        </div>
      </div>
    </div>
  )
}
