"use client"

import { ChevronDown, Lightbulb } from "lucide-react"
import { cn } from "@/lib/utils"

interface IdeaBriefSectionProps {
  isActive: boolean
  onToggle: () => void
  value: string
  onChange: (value: string) => void
}

export function IdeaBriefSection({ isActive, onToggle, value, onChange }: IdeaBriefSectionProps) {
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-amber-500/10 flex items-center justify-center">
            <Lightbulb className="h-4 w-4 text-amber-500" />
          </div>
          <div className="text-left">
            <h3 className="font-medium">Idea Brief</h3>
            <p className="text-sm text-muted-foreground">
              {value ? "Hypothesis captured" : "Describe your trading hypothesis in plain English"}
            </p>
          </div>
        </div>
        <ChevronDown className={cn("h-5 w-5 text-muted-foreground transition-transform", isActive && "rotate-180")} />
      </button>
      
      {isActive && (
        <div className="px-4 pb-4 border-t border-border pt-4">
          <textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Example: I think BTC continuation near close is mispriced when Coinbase momentum is strong and Kalshi spread is tight."
            className="w-full h-32 bg-muted rounded-lg p-4 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <p className="text-xs text-muted-foreground mt-2">
            This helps document your thinking. The system will suggest structured fields based on your brief.
          </p>
        </div>
      )}
    </div>
  )
}
