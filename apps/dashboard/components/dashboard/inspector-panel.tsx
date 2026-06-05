'use client'

import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { StatusBadge } from '@/components/ui/status-badge'
import { ExternalLink, Copy, ChevronRight, PanelRightClose, PanelRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DecisionChainStep, Artifact, SystemHealth } from '@/lib/mock-data'

interface InspectorPanelProps {
  runId?: string
  marketTicker?: string
  configVersion?: string
  modelVersion?: string
  decisionChain: DecisionChainStep[]
  artifacts: Artifact[]
  systemHealth: SystemHealth[]
}

export function InspectorPanel({
  runId = 'fv_live_20260604T233310Z',
  marketTicker = 'KXBTC15M',
  configVersion = 'dashboard_postgres v2',
  modelVersion = 'threshold_volatility_fair_value.v1',
  decisionChain,
  artifacts,
  systemHealth,
}: InspectorPanelProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  return (
    <aside
      className={cn(
        'flex h-full flex-col border-l border-border bg-card transition-all duration-200',
        isCollapsed ? 'w-10' : 'w-[280px]'
      )}
    >
      <div className="flex h-10 items-center justify-between border-b border-border px-3">
        {!isCollapsed && (
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Run Inspector
          </span>
        )}
        <div className={cn('flex items-center gap-1', isCollapsed && 'w-full justify-center')}>
          {!isCollapsed && (
            <button className="text-muted-foreground hover:text-foreground">
              <ExternalLink className="h-3 w-3" />
            </button>
          )}
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="text-muted-foreground hover:text-foreground"
            aria-label={isCollapsed ? 'Expand inspector' : 'Collapse inspector'}
          >
            {isCollapsed ? (
              <PanelRight className="h-4 w-4" />
            ) : (
              <PanelRightClose className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>

      {isCollapsed ? (
        <div className="flex flex-1 flex-col items-center gap-2 pt-3">
          <div className="h-2 w-2 rounded-full bg-success" title="System healthy" />
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="space-y-4 p-3">
            {/* Run Info */}
            <div>
              <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Run Details
              </h4>
              <div className="space-y-1.5 text-[10px]">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Run ID</span>
                  <div className="flex items-center gap-1">
                    <span className="font-mono text-foreground">{runId.slice(0, 20)}...</span>
                    <button className="text-muted-foreground hover:text-foreground">
                      <Copy className="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Market</span>
                  <Badge variant="outline" className="h-4 rounded px-1 font-mono text-[9px]">
                    {marketTicker}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Config</span>
                  <span className="font-mono text-foreground">{configVersion}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Model</span>
                  <span className="font-mono text-foreground">{modelVersion.split('.')[0]}</span>
                </div>
              </div>
            </div>

            <Separator />

            {/* Decision Chain */}
            <div>
              <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Decision Chain
              </h4>
              <div className="space-y-0.5">
                {decisionChain.map((step) => (
                  <div
                    key={step.step}
                    className={cn(
                      'flex items-center gap-2 rounded px-2 py-1 text-[10px]',
                      step.status === 'blocked'
                        ? 'bg-warning/10'
                        : step.status === 'skipped'
                          ? 'bg-secondary/30'
                          : 'bg-secondary/50'
                    )}
                  >
                    <div
                      className={cn(
                        'h-1.5 w-1.5 rounded-full',
                        step.status === 'ok'
                          ? 'bg-success'
                          : step.status === 'blocked'
                            ? 'bg-warning'
                            : 'bg-muted-foreground/50'
                      )}
                    />
                    <span
                      className={
                        step.status === 'skipped' ? 'text-muted-foreground' : 'text-foreground'
                      }
                    >
                      {step.step}
                    </span>
                    <span className="ml-auto font-mono text-[9px] text-muted-foreground">
                      {step.detail}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <Separator />

            {/* Artifacts */}
            <div>
              <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Artifacts
              </h4>
              <div className="space-y-1">
                {artifacts.map((artifact) => (
                  <button
                    key={artifact.name}
                    className="flex w-full items-center justify-between rounded bg-secondary/50 px-2 py-1.5 text-[10px] hover:bg-secondary"
                  >
                    <span>{artifact.name}</span>
                    <div className="flex items-center gap-1.5">
                      <Badge variant="outline" className="h-3.5 rounded px-1 font-mono text-[8px]">
                        {artifact.type}
                      </Badge>
                      <ChevronRight className="h-3 w-3 text-muted-foreground" />
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <Separator />

            {/* Health Status */}
            <div>
              <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                System Health
              </h4>
              <div className="grid grid-cols-2 gap-1.5 text-[9px]">
                {systemHealth.map((system) => (
                  <div
                    key={system.name}
                    className="flex items-center gap-1.5 rounded bg-secondary/50 px-2 py-1"
                  >
                    <StatusBadge variant={system.ok ? 'ok' : 'error'} dot size="sm">
                      {system.name}
                    </StatusBadge>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ScrollArea>
      )}
    </aside>
  )
}
