"use client"

import { SideNav } from "@/components/nav/side-nav"
import { AgentTerminal } from "@/components/terminal/agent-terminal"
import { ReactNode } from "react"

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex h-screen bg-background">
      <SideNav />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-auto">
          {children}
        </main>
        <AgentTerminal />
      </div>
    </div>
  )
}
