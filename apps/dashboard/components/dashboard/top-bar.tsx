'use client'

import { Badge } from '@/components/ui/badge'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Circle, Search, Bell, User } from 'lucide-react'

interface TopBarProps {
  environment?: string
  runtimeMode?: string
  authority?: string
  liveOrdersGate?: 'enabled' | 'disabled'
  health?: 'healthy' | 'degraded' | 'unhealthy'
  latestRunTime?: string
}

export function TopBar({
  environment = 'production',
  runtimeMode = 'gated-live',
  authority = 'Current MVP',
  liveOrdersGate = 'disabled',
  health = 'healthy',
  latestRunTime = '2026-06-04T23:33:10Z',
}: TopBarProps) {
  const healthColor = {
    healthy: 'bg-success',
    degraded: 'bg-warning',
    unhealthy: 'bg-destructive',
  }[health]

  return (
    <header className="flex h-10 items-center justify-between border-b border-border bg-card px-4">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="h-5 gap-1 rounded px-1.5 text-[10px] font-medium uppercase">
            <Circle className={`h-1.5 w-1.5 fill-current ${environment === 'production' ? 'text-success' : 'text-warning'}`} />
            {environment}
          </Badge>
          <Badge variant="outline" className="h-5 rounded px-1.5 text-[10px] font-mono">
            {runtimeMode}
          </Badge>
        </div>

        <div className="h-4 w-px bg-border" />

        <Tooltip>
          <TooltipTrigger className="flex items-center gap-1.5 text-[10px] text-muted-foreground cursor-default">
            <span className="uppercase tracking-wide">Authority:</span>
            <span className="font-medium text-foreground">{authority}</span>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Current MVP remains authoritative until cutover
          </TooltipContent>
        </Tooltip>

        <div className="h-4 w-px bg-border" />

        <div className="flex items-center gap-1.5 text-[10px]">
          <span className="uppercase tracking-wide text-muted-foreground">Live Orders:</span>
          <Badge 
            variant={liveOrdersGate === 'enabled' ? 'default' : 'secondary'} 
            className={`h-4 rounded px-1 text-[9px] font-medium ${liveOrdersGate === 'enabled' ? 'bg-success text-success-foreground' : ''}`}
          >
            {liveOrdersGate}
          </Badge>
        </div>

        <div className="h-4 w-px bg-border" />

        <Tooltip>
          <TooltipTrigger className="flex items-center gap-1.5 text-[10px] cursor-default">
            <span className="uppercase tracking-wide text-muted-foreground">Health:</span>
            <div className={`h-2 w-2 rounded-full ${healthColor}`} />
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            All systems operational
          </TooltipContent>
        </Tooltip>

        <div className="h-4 w-px bg-border" />

        <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <span className="uppercase tracking-wide">Last Run:</span>
          <span className="font-mono text-foreground">{latestRunTime.split('T')[1].replace('Z', '')}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button className="flex h-7 w-48 items-center gap-2 rounded border border-border bg-secondary px-2.5 text-xs text-muted-foreground hover:bg-accent">
          <Search className="h-3 w-3" />
          <span>Search runs, markets...</span>
          <kbd className="ml-auto rounded bg-muted px-1 text-[9px] font-mono">⌘K</kbd>
        </button>
        <button className="relative flex h-7 w-7 items-center justify-center rounded hover:bg-accent">
          <Bell className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
        <button className="flex h-7 w-7 items-center justify-center rounded hover:bg-accent">
          <User className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
      </div>
    </header>
  )
}
