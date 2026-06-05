"use client"

import { ChevronDown, Shield, Check, Circle, Lock } from "lucide-react"
import { cn } from "@/lib/utils"
import { StrategyDraft } from "@/app/strategies/new/page"

interface PromotionSectionProps {
  isActive: boolean
  onToggle: () => void
  currentStage: StrategyDraft["promotionStage"]
}

const stages = [
  { 
    id: "draft" as const, 
    name: "Draft", 
    description: "Strategy definition in progress",
    blockers: []
  },
  { 
    id: "replay" as const, 
    name: "Replay", 
    description: "Historical simulation with no-lookahead validation",
    blockers: ["All fields required", "Inputs configured", "Valid expression"]
  },
  { 
    id: "shadow" as const, 
    name: "Shadow", 
    description: "Live market tracking without execution",
    blockers: ["Replay pass: no-lookahead", "Replay metrics reviewed"]
  },
  { 
    id: "paper" as const, 
    name: "Paper", 
    description: "Simulated execution with paper balance",
    blockers: ["Shadow run complete", "Coverage 100%"]
  },
  { 
    id: "gated-live" as const, 
    name: "Gated Live", 
    description: "Real execution with human approval per trade",
    blockers: ["Paper results reviewed", "Risk config set", "Human approval"]
  },
  { 
    id: "live" as const, 
    name: "Live", 
    description: "Fully autonomous execution",
    blockers: ["Gated-live track record", "Final human sign-off"]
  },
]

export function PromotionSection({ 
  isActive, 
  onToggle, 
  currentStage,
}: PromotionSectionProps) {
  const currentIndex = stages.findIndex(s => s.id === currentStage)
  const currentStageData = stages[currentIndex]

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-cyan-500/10 flex items-center justify-center">
            <Shield className="h-4 w-4 text-cyan-500" />
          </div>
          <div className="text-left">
            <h3 className="font-medium">Proof & Promotion</h3>
            <p className="text-sm text-muted-foreground">
              Stage: {currentStageData.name}
            </p>
          </div>
        </div>
        <ChevronDown className={cn("h-5 w-5 text-muted-foreground transition-transform", isActive && "rotate-180")} />
      </button>
      
      {isActive && (
        <div className="px-4 pb-4 border-t border-border pt-4 space-y-6">
          {/* Promotion Ladder */}
          <div>
            <label className="text-sm font-medium mb-4 block">Promotion Ladder</label>
            <div className="relative">
              {/* Connecting line */}
              <div className="absolute left-4 top-6 bottom-6 w-px bg-border" />
              
              <div className="space-y-1">
                {stages.map((stage, index) => {
                  const isPast = index < currentIndex
                  const isCurrent = index === currentIndex
                  const isFuture = index > currentIndex
                  
                  return (
                    <div key={stage.id} className="relative flex items-start gap-4 py-2">
                      {/* Stage indicator */}
                      <div className={cn(
                        "relative z-10 h-8 w-8 rounded-full flex items-center justify-center shrink-0",
                        isPast && "bg-emerald-500",
                        isCurrent && "bg-primary",
                        isFuture && "bg-muted border border-border"
                      )}>
                        {isPast && <Check className="h-4 w-4 text-white" />}
                        {isCurrent && <Circle className="h-3 w-3 text-primary-foreground fill-primary-foreground" />}
                        {isFuture && <Lock className="h-3 w-3 text-muted-foreground" />}
                      </div>
                      
                      {/* Stage info */}
                      <div className="flex-1 pt-1">
                        <div className="flex items-center gap-2">
                          <p className={cn(
                            "font-medium text-sm",
                            isFuture && "text-muted-foreground"
                          )}>
                            {stage.name}
                          </p>
                          {isCurrent && (
                            <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded">
                              Current
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {stage.description}
                        </p>
                        
                        {/* Blockers for next stage */}
                        {isCurrent && index < stages.length - 1 && (
                          <div className="mt-2">
                            <p className="text-xs text-muted-foreground mb-1">
                              To advance to {stages[index + 1].name}:
                            </p>
                            <ul className="space-y-1">
                              {stages[index + 1].blockers.map((blocker) => (
                                <li key={blocker} className="flex items-center gap-2 text-xs">
                                  <div className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                                  <span className="text-muted-foreground">{blocker}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
          
          {/* Current Stage Actions */}
          <div className="bg-muted rounded-lg p-4">
            <p className="text-sm font-medium mb-2">Next Step</p>
            {currentStage === "draft" && (
              <p className="text-sm text-muted-foreground">
                Complete all required fields, then run Replay to validate the strategy against historical data.
              </p>
            )}
            {currentStage === "replay" && (
              <p className="text-sm text-muted-foreground">
                Review replay metrics and no-lookahead validation results, then promote to Shadow mode.
              </p>
            )}
            {currentStage === "shadow" && (
              <p className="text-sm text-muted-foreground">
                Monitor shadow decisions against live markets to verify behavior before paper trading.
              </p>
            )}
            {currentStage === "paper" && (
              <p className="text-sm text-muted-foreground">
                Review paper trading results and configure risk parameters before gated-live execution.
              </p>
            )}
            {currentStage === "gated-live" && (
              <p className="text-sm text-muted-foreground">
                Approve or reject individual trades to build confidence before full autonomy.
              </p>
            )}
            {currentStage === "live" && (
              <p className="text-sm text-emerald-500">
                Strategy is fully autonomous. Monitor performance and adjust as needed.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
