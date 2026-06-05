'use client'

import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { StatusBadge } from '@/components/ui/status-badge'
import { CheckCircle2, XCircle, AlertCircle, Clock, ArrowRight } from 'lucide-react'
import type { OperatingState, RiskMetric, Decision, Order, EvidenceItem } from '@/lib/mock-data'

interface StatusPanelProps {
  className?: string
}

interface CurrentStatePanelProps extends StatusPanelProps {
  data: OperatingState
}

export function CurrentStatePanel({ className, data }: CurrentStatePanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Current Operating State
        </h3>
        <StatusBadge variant="live" size="sm">LIVE</StatusBadge>
      </div>

      <div className="space-y-1.5 text-xs">
        <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
          <span className="text-muted-foreground">Status</span>
          <StatusBadge variant="warning">{data.status}</StatusBadge>
        </div>
        <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
          <span className="text-muted-foreground">Latest Run</span>
          <span className="font-mono text-[10px] text-foreground">{data.latestRunId}</span>
        </div>
        <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
          <span className="text-muted-foreground">Decision</span>
          <span className="text-warning">{data.decision}</span>
        </div>
        {data.skipReason && (
          <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
            <span className="text-muted-foreground">Skip Reason</span>
            <span className="font-mono text-[10px] text-muted-foreground">{data.skipReason}</span>
          </div>
        )}
      </div>
    </div>
  )
}

interface StrategyRunnerPanelProps extends StatusPanelProps {
  mode: string
  configVersion: string
  modelVersion: string
}

export function StrategyRunnerPanel({
  className,
  mode,
  configVersion,
  modelVersion,
}: StrategyRunnerPanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Strategy Runner
        </h3>
        <StatusBadge variant="ok" dot pulse>Running</StatusBadge>
      </div>

      <div className="space-y-1.5 text-xs">
        <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
          <span className="text-muted-foreground">Mode</span>
          <Badge variant="outline" className="h-4 rounded px-1 font-mono text-[9px]">
            {mode}
          </Badge>
        </div>
        <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
          <span className="text-muted-foreground">Config</span>
          <span className="font-mono text-[10px]">{configVersion}</span>
        </div>
        <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
          <span className="text-muted-foreground">Model</span>
          <span className="font-mono text-[10px]">{modelVersion}</span>
        </div>
        <div className="flex items-center justify-between rounded bg-secondary/50 px-2 py-1.5">
          <span className="text-muted-foreground">Next Run</span>
          <span className="font-mono text-[10px]">~14s</span>
        </div>
      </div>

      <div className="mt-3 flex gap-1.5">
        <button className="flex-1 rounded border border-border bg-secondary px-2 py-1 text-[10px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground">
          Pause
        </button>
        <button className="flex-1 rounded border border-border bg-secondary px-2 py-1 text-[10px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground">
          Dry Run
        </button>
        <button className="flex-1 rounded border border-destructive/50 bg-destructive/10 px-2 py-1 text-[10px] font-medium text-destructive hover:bg-destructive/20">
          Stop
        </button>
      </div>
    </div>
  )
}

interface RiskGuardrailsPanelProps extends StatusPanelProps {
  data: RiskMetric[]
}

export function RiskGuardrailsPanel({ className, data }: RiskGuardrailsPanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Risk Guardrails
        </h3>
        <StatusBadge variant="inactive" size="sm">{data.length} active</StatusBadge>
      </div>

      <div className="space-y-2">
        {data.map((metric) => (
          <div key={metric.label} className="space-y-1">
            <div className="flex items-center justify-between text-[10px]">
              <span className="text-muted-foreground">{metric.label}</span>
              <span className="font-mono">
                <span className={metric.status === 'warning' ? 'text-warning' : 'text-foreground'}>
                  {metric.current}
                </span>
                <span className="text-muted-foreground"> / {metric.limit}</span>
              </span>
            </div>
            <div className="h-1 rounded-full bg-secondary">
              <div
                className={`h-1 rounded-full ${
                  metric.usage > 90 ? 'bg-warning' : metric.usage > 75 ? 'bg-chart-1' : 'bg-success'
                }`}
                style={{ width: `${Math.min(metric.usage, 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

interface RecentDecisionsPanelProps extends StatusPanelProps {
  data: Decision[]
}

const decisionIcons = {
  skipped: { icon: AlertCircle, color: 'text-warning' },
  filled: { icon: CheckCircle2, color: 'text-success' },
  submitted: { icon: Clock, color: 'text-chart-1' },
  rejected: { icon: XCircle, color: 'text-destructive' },
}

export function RecentDecisionsPanel({ className, data }: RecentDecisionsPanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Recent Decisions
        </h3>
        <button className="text-[9px] text-muted-foreground hover:text-foreground">View all</button>
      </div>

      <ScrollArea className="h-[140px]">
        <div className="space-y-1">
          {data.map((d, i) => {
            const config = decisionIcons[d.decision]
            const Icon = config.icon
            return (
              <div
                key={i}
                className="flex items-center gap-2 rounded bg-secondary/50 px-2 py-1.5 text-[10px]"
              >
                <span className="font-mono text-muted-foreground">{d.time}</span>
                <Icon className={`h-3 w-3 ${config.color}`} />
                <span className={config.color}>{d.decision}</span>
                {d.reason && (
                  <>
                    <ArrowRight className="h-2.5 w-2.5 text-muted-foreground" />
                    <span className="font-mono text-muted-foreground">{d.reason}</span>
                  </>
                )}
              </div>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}

interface OrderAttemptsPanelProps extends StatusPanelProps {
  data: Order[]
}

export function OrderAttemptsPanel({ className, data }: OrderAttemptsPanelProps) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Order Attempts
        </h3>
        <StatusBadge variant="ok" size="sm">{data.length} today</StatusBadge>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="pb-1.5 font-medium">ID</th>
              <th className="pb-1.5 font-medium">Time</th>
              <th className="pb-1.5 font-medium">Side</th>
              <th className="pb-1.5 font-medium">Size</th>
              <th className="pb-1.5 font-medium">Status</th>
              <th className="pb-1.5 font-medium">Fill</th>
            </tr>
          </thead>
          <tbody>
            {data.map((order) => (
              <tr key={order.id} className="border-b border-border/50">
                <td className="py-1.5 font-mono text-muted-foreground">{order.id}</td>
                <td className="py-1.5 font-mono">{order.time}</td>
                <td className={`py-1.5 ${order.side === 'YES' ? 'text-success' : 'text-destructive'}`}>
                  {order.side}
                </td>
                <td className="py-1.5 font-mono">{order.size}</td>
                <td className="py-1.5">
                  <StatusBadge
                    variant={order.status === 'filled' ? 'ok' : 'warning'}
                    size="sm"
                  >
                    {order.status}
                  </StatusBadge>
                </td>
                <td className="py-1.5 font-mono">{order.fill}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface EvidenceReadinessPanelProps extends StatusPanelProps {
  data: EvidenceItem[]
}

const evidenceStatusConfig = {
  pass: { icon: CheckCircle2, color: 'text-success', bg: 'bg-success/10' },
  fail: { icon: XCircle, color: 'text-destructive', bg: 'bg-destructive/10' },
  pending: { icon: Clock, color: 'text-warning', bg: 'bg-warning/10' },
}

export function EvidenceReadinessPanel({ className, data }: EvidenceReadinessPanelProps) {
  const passCount = data.filter((item) => item.status === 'pass').length
  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Evidence Readiness
        </h3>
        <StatusBadge variant="inactive" size="sm">
          {passCount}/{data.length} pass
        </StatusBadge>
      </div>

      <div className="space-y-1.5">
        {data.map((item) => {
          const config = evidenceStatusConfig[item.status]
          return (
            <div
              key={item.name}
              className={`flex items-center justify-between rounded px-2 py-1.5 ${config.bg}`}
            >
              <div className="flex items-center gap-2">
                <config.icon className={`h-3 w-3 ${config.color}`} />
                <span className="text-[10px]">{item.name}</span>
              </div>
              <span className="text-[9px] text-muted-foreground">{item.detail}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
