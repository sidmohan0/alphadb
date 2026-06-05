"use client"

import { AgentStatus } from "@/lib/skills/types"
import { ChevronDown, ChevronUp, Minus, Square, Terminal } from "lucide-react"
import { cn } from "@/lib/utils"

interface TerminalHeaderProps {
  status: AgentStatus
  isExpanded: boolean
  isMinimized: boolean
  onToggleExpand: () => void
  onMinimize: () => void
}

export function TerminalHeader({
  status,
  isExpanded,
  isMinimized,
  onToggleExpand,
  onMinimize,
}: TerminalHeaderProps) {
  const statusConfig: Record<AgentStatus, { color: string; label: string; pulse?: boolean }> = {
    idle: { color: "bg-muted-foreground", label: "Ready" },
    thinking: { color: "bg-amber-500", label: "Thinking...", pulse: true },
    acting: { color: "bg-primary", label: "Acting...", pulse: true },
    error: { color: "bg-destructive", label: "Error" },
    disconnected: { color: "bg-muted-foreground/50", label: "Disconnected" },
  }

  const { color, label, pulse } = statusConfig[status]

  return (
    <div className="flex items-center justify-between px-3 py-2 bg-card/80 border-b border-border">
      <div className="flex items-center gap-2">
        <Terminal className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs font-medium text-foreground">Agent</span>
        <div className="flex items-center gap-1.5 ml-2">
          <div
            className={cn(
              "h-2 w-2 rounded-full",
              color,
              pulse && "animate-pulse"
            )}
          />
          <span className="text-xs text-muted-foreground">{label}</span>
        </div>
      </div>
      
      <div className="flex items-center gap-1">
        <button
          onClick={onToggleExpand}
          className="p-1 text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
          title={isExpanded ? "Collapse" : "Expand"}
        >
          {isExpanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronUp className="h-4 w-4" />
          )}
        </button>
        <button
          onClick={onMinimize}
          className="p-1 text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
          title="Minimize"
        >
          {isMinimized ? (
            <Square className="h-3 w-3" />
          ) : (
            <Minus className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  )
}
