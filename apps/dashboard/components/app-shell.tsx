"use client"

import { SideNav } from "@/components/nav/side-nav"
import { StrategyProvider, useSelectedStrategy, type LiveStrategy } from "@/components/strategy/strategy-context"
import { AgentTerminal } from "@/components/terminal/agent-terminal"
import { FieldLabel, Select } from "@/components/ui/field"
import { ReactNode } from "react"

interface AppShellProps {
  children: ReactNode
  showStrategySelector?: boolean
}

export function AppShell({ children, showStrategySelector = true }: AppShellProps) {
  return (
    <StrategyProvider>
      <div className="flex h-screen bg-background">
        <SideNav />
        <div className="flex-1 flex flex-col overflow-hidden">
          <GlobalHeader showStrategySelector={showStrategySelector} />
          <main className="flex-1 overflow-auto">
            {children}
          </main>
          <AgentTerminal />
        </div>
      </div>
    </StrategyProvider>
  )
}

function GlobalHeader({ showStrategySelector }: { showStrategySelector: boolean }) {
  const { selectedStrategy, setSelectedStrategy, strategies } = useSelectedStrategy()

  return (
    <header className="flex h-12 shrink-0 items-center justify-end border-b border-border bg-background px-4">
      {showStrategySelector && (
        <label className="flex items-center gap-2">
          <FieldLabel>Strategy</FieldLabel>
          <Select
            className="w-auto min-w-40"
            value={selectedStrategy}
            onChange={(event) => setSelectedStrategy(event.target.value as LiveStrategy)}
          >
            {strategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id}>
                {strategy.label}
              </option>
            ))}
          </Select>
        </label>
      )}
    </header>
  )
}
