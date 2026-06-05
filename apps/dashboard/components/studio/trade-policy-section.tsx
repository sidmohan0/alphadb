"use client"

import { ChevronDown, TrendingUp, Plus, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { StrategyDraft } from "@/app/strategies/new/page"

interface TradePolicySectionProps {
  isActive: boolean
  onToggle: () => void
  tradePolicy: StrategyDraft["tradePolicy"]
  onChange: (tradePolicy: StrategyDraft["tradePolicy"]) => void
}

export function TradePolicySection({ 
  isActive, 
  onToggle, 
  tradePolicy,
  onChange 
}: TradePolicySectionProps) {
  const addSkipCondition = () => {
    const newCondition = prompt("Enter skip condition (e.g., 'spread > 10c')")
    if (newCondition) {
      onChange({ ...tradePolicy, skipConditions: [...tradePolicy.skipConditions, newCondition] })
    }
  }
  
  const removeSkipCondition = (condition: string) => {
    onChange({ 
      ...tradePolicy, 
      skipConditions: tradePolicy.skipConditions.filter(c => c !== condition) 
    })
  }

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-orange-500/10 flex items-center justify-center">
            <TrendingUp className="h-4 w-4 text-orange-500" />
          </div>
          <div className="text-left">
            <h3 className="font-medium">Trade Policy</h3>
            <p className="text-sm text-muted-foreground">
              {tradePolicy.side} side, {tradePolicy.minEdgeCents}c edge, ${tradePolicy.maxDollars} max
            </p>
          </div>
        </div>
        <ChevronDown className={cn("h-5 w-5 text-muted-foreground transition-transform", isActive && "rotate-180")} />
      </button>
      
      {isActive && (
        <div className="px-4 pb-4 border-t border-border pt-4 space-y-6">
          {/* Side Selection */}
          <div>
            <label className="text-sm font-medium mb-2 block">Trade Side</label>
            <div className="grid grid-cols-3 gap-2">
              {(["YES", "NO", "best"] as const).map((side) => (
                <button
                  key={side}
                  onClick={() => onChange({ ...tradePolicy, side })}
                  className={cn(
                    "p-3 rounded-lg border transition-colors text-center",
                    tradePolicy.side === side 
                      ? "border-primary bg-primary/5" 
                      : "border-border hover:border-muted-foreground/50"
                  )}
                >
                  <p className="font-medium text-sm">{side === "best" ? "Best Side" : side}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {side === "YES" && "Only buy YES contracts"}
                    {side === "NO" && "Only buy NO contracts"}
                    {side === "best" && "Buy whichever has better EV"}
                  </p>
                </button>
              ))}
            </div>
          </div>
          
          {/* Edge & Sizing */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-2 block">Minimum Edge (cents)</label>
              <p className="text-xs text-muted-foreground mb-2">
                Skip if expected value after fees is below this.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={0}
                  max={5}
                  step={0.1}
                  value={tradePolicy.minEdgeCents}
                  onChange={(e) => onChange({ ...tradePolicy, minEdgeCents: parseFloat(e.target.value) })}
                  className="flex-1"
                />
                <span className="font-mono text-sm w-12 text-right">{tradePolicy.minEdgeCents}c</span>
              </div>
            </div>
            
            <div>
              <label className="text-sm font-medium mb-2 block">Max Dollars per Market</label>
              <p className="text-xs text-muted-foreground mb-2">
                Position size cap for a single market instance.
              </p>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={1}
                  max={50}
                  step={1}
                  value={tradePolicy.maxDollars}
                  onChange={(e) => onChange({ ...tradePolicy, maxDollars: parseInt(e.target.value) })}
                  className="flex-1"
                />
                <span className="font-mono text-sm w-12 text-right">${tradePolicy.maxDollars}</span>
              </div>
            </div>
          </div>
          
          {/* Execution Mode */}
          <div>
            <label className="text-sm font-medium mb-2 block">Execution Mode</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => onChange({ ...tradePolicy, executionMode: "taker-ioc" })}
                className={cn(
                  "p-3 rounded-lg border transition-colors text-left",
                  tradePolicy.executionMode === "taker-ioc" 
                    ? "border-primary bg-primary/5" 
                    : "border-border hover:border-muted-foreground/50"
                )}
              >
                <p className="font-medium text-sm">Taker IOC</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Immediate-or-cancel at market. Fast execution, pays spread.
                </p>
              </button>
              <button
                onClick={() => onChange({ ...tradePolicy, executionMode: "maker" })}
                className={cn(
                  "p-3 rounded-lg border transition-colors text-left",
                  tradePolicy.executionMode === "maker" 
                    ? "border-primary bg-primary/5" 
                    : "border-border hover:border-muted-foreground/50"
                )}
              >
                <p className="font-medium text-sm">Maker</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Post limit order. Better price, may not fill.
                </p>
              </button>
            </div>
          </div>
          
          {/* Skip Conditions */}
          <div>
            <label className="text-sm font-medium mb-2 block">Skip Conditions</label>
            <p className="text-xs text-muted-foreground mb-2">
              Force skip when any of these conditions are true.
            </p>
            <div className="flex flex-wrap gap-2 mb-2">
              {tradePolicy.skipConditions.map((condition) => (
                <span 
                  key={condition} 
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-red-500/10 text-red-400 rounded-full text-sm font-mono"
                >
                  {condition}
                  <button 
                    onClick={() => removeSkipCondition(condition)}
                    className="hover:text-red-300"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
            <button
              onClick={addSkipCondition}
              className="inline-flex items-center gap-1 px-2.5 py-1 border border-dashed border-border rounded-full text-sm text-muted-foreground hover:text-foreground hover:border-muted-foreground/50 transition-colors"
            >
              <Plus className="h-3 w-3" />
              Add condition
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
