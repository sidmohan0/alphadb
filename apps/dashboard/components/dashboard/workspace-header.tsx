'use client'

import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface WorkspaceHeaderProps {
  strategyName?: string
  marketTicker?: string
  activeTab?: string
  onTabChange?: (tab: string) => void
}

export function WorkspaceHeader({
  strategyName = 'KXBTC15M fair value',
  marketTicker = 'KXBTC15M',
  activeTab = 'overview',
  onTabChange,
}: WorkspaceHeaderProps) {
  return (
    <div className="border-b border-border bg-card px-4 py-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold text-foreground">{strategyName}</h1>
          <Badge variant="outline" className="h-5 rounded px-1.5 font-mono text-[10px]">
            {marketTicker}
          </Badge>
          <Badge className="h-5 rounded bg-warning/20 px-1.5 text-[10px] text-warning hover:bg-warning/30">
            gated-live
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <button className="h-6 rounded border border-border bg-secondary px-2 text-[10px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground">
            Pin Workspace
          </button>
        </div>
      </div>
      
      <Tabs value={activeTab} onValueChange={onTabChange} className="mt-2">
        <TabsList className="h-7 gap-0 rounded-none border-b-0 bg-transparent p-0">
          {['Overview', 'Decisions', 'Orders', 'Positions', 'History', 'Evidence', 'Config'].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab.toLowerCase()}
              className="h-7 rounded-none border-b-2 border-transparent px-3 text-[11px] data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    </div>
  )
}
