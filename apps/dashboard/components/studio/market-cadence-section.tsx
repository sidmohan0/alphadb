"use client"

import { ChevronDown, Clock } from "lucide-react"
import { cn } from "@/lib/utils"

interface MarketCadenceSectionProps {
  isActive: boolean
  onToggle: () => void
  marketFamily: string
  decisionMinute: number
  onChange: (updates: { marketFamily?: string; decisionMinute?: number }) => void
}

const marketFamilies = [
  { id: "KXBTC15M", name: "BTC 15-Minute", description: "Bitcoin price above/below threshold every 15 minutes" },
  { id: "KXBTC1H", name: "BTC Hourly", description: "Bitcoin price above/below threshold every hour" },
  { id: "KXETH15M", name: "ETH 15-Minute", description: "Ethereum price above/below threshold every 15 minutes" },
]

export function MarketCadenceSection({ 
  isActive, 
  onToggle, 
  marketFamily, 
  decisionMinute, 
  onChange 
}: MarketCadenceSectionProps) {
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-blue-500/10 flex items-center justify-center">
            <Clock className="h-4 w-4 text-blue-500" />
          </div>
          <div className="text-left">
            <h3 className="font-medium">Market & Cadence</h3>
            <p className="text-sm text-muted-foreground">
              {marketFamily} at minute {decisionMinute}
            </p>
          </div>
        </div>
        <ChevronDown className={cn("h-5 w-5 text-muted-foreground transition-transform", isActive && "rotate-180")} />
      </button>
      
      {isActive && (
        <div className="px-4 pb-4 border-t border-border pt-4 space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Market Family</label>
            <div className="grid gap-2">
              {marketFamilies.map((mf) => (
                <button
                  key={mf.id}
                  onClick={() => onChange({ marketFamily: mf.id })}
                  className={cn(
                    "flex items-start gap-3 p-3 rounded-lg border text-left transition-colors",
                    marketFamily === mf.id 
                      ? "border-primary bg-primary/5" 
                      : "border-border hover:border-muted-foreground/50"
                  )}
                >
                  <div className={cn(
                    "h-4 w-4 rounded-full border-2 mt-0.5 shrink-0",
                    marketFamily === mf.id ? "border-primary bg-primary" : "border-muted-foreground/30"
                  )} />
                  <div>
                    <p className="font-medium text-sm">{mf.name}</p>
                    <p className="text-xs text-muted-foreground">{mf.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>
          
          <div>
            <label className="text-sm font-medium mb-2 block">Decision Minute</label>
            <p className="text-xs text-muted-foreground mb-2">
              When in the 15-minute cycle should the strategy evaluate?
            </p>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={0}
                max={14}
                value={decisionMinute}
                onChange={(e) => onChange({ decisionMinute: parseInt(e.target.value) })}
                className="flex-1"
              />
              <span className="font-mono text-sm w-16 text-right">:{String(decisionMinute).padStart(2, "0")}</span>
            </div>
            <div className="flex justify-between text-xs text-muted-foreground mt-1">
              <span>:00 (cycle start)</span>
              <span>:14 (before close)</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
