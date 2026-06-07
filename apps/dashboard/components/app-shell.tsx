"use client"

import { SideNav } from "@/components/nav/side-nav"
import { StrategyProvider, useSelectedStrategy, type LiveStrategy } from "@/components/strategy/strategy-context"
import { AgentTerminal } from "@/components/terminal/agent-terminal"
import { ReactNode } from "react"

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <StrategyProvider>
      <div className="flex h-screen bg-background">
        <SideNav />
        <div className="flex-1 flex flex-col overflow-hidden">
          <GlobalHeader />
          <main className="flex-1 overflow-auto">
            {children}
          </main>
          <AgentTerminal />
        </div>
      </div>
    </StrategyProvider>
  )
}

function GlobalHeader() {
  const { selectedStrategy, setSelectedStrategy, strategies } = useSelectedStrategy()

  return (
    <header className="flex h-12 shrink-0 items-center justify-end border-b border-border bg-background px-4">
      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>Strategy</span>
        <select
          className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/30"
          value={selectedStrategy}
          onChange={(event) => setSelectedStrategy(event.target.value as LiveStrategy)}
        >
          {strategies.map((strategy) => (
            <option key={strategy.id} value={strategy.id}>
              {strategy.label}
            </option>
          ))}
        </select>
      </label>
    </header>
  )
}
