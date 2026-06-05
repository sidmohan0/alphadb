"use client"

import { StrategyDraft } from "@/app/strategies/new/page"
import { cn } from "@/lib/utils"

interface StrategySentenceProps {
  draft: StrategyDraft
  onFieldClick: (field: string) => void
}

export function StrategySentence({ draft, onFieldClick }: StrategySentenceProps) {
  const ClickableField = ({ 
    value, 
    field, 
    className 
  }: { 
    value: string
    field: string
    className?: string 
  }) => (
    <button
      onClick={() => onFieldClick(field)}
      className={cn(
        "px-1.5 py-0.5 rounded bg-muted hover:bg-muted/80 text-foreground font-medium transition-colors",
        "border border-transparent hover:border-border",
        className
      )}
    >
      {value}
    </button>
  )

  const beliefDescription = () => {
    switch (draft.beliefMode) {
      case "rules":
        return "structural rules"
      case "formula":
        return "fair-value formula"
      case "model":
        return "ML model"
    }
  }

  return (
    <div className="bg-card border border-border rounded-lg p-6">
      <p className="text-sm text-muted-foreground mb-3">Strategy Contract</p>
      <p className="text-lg leading-relaxed">
        For every{" "}
        <ClickableField 
          value={draft.marketFamily || "market"} 
          field="market-cadence" 
        />{" "}
        instance, at minute{" "}
        <ClickableField 
          value={String(draft.decisionMinute)} 
          field="market-cadence" 
        />
        , use{" "}
        <ClickableField 
          value={draft.inputs.length > 0 ? draft.inputs.join(" + ") : "inputs"} 
          field="belief-builder" 
        />{" "}
        to estimate{" "}
        <ClickableField 
          value="YES probability" 
          field="belief-builder" 
        />{" "}
        via{" "}
        <ClickableField 
          value={beliefDescription()} 
          field="belief-builder" 
        />
        , then buy the{" "}
        <ClickableField 
          value={draft.tradePolicy.side} 
          field="trade-policy" 
        />{" "}
        side when EV after taker fees exceeds{" "}
        <ClickableField 
          value={`${draft.tradePolicy.minEdgeCents}c`} 
          field="trade-policy" 
        />
        , capped at{" "}
        <ClickableField 
          value={`$${draft.tradePolicy.maxDollars}`} 
          field="trade-policy" 
        />{" "}
        per market, otherwise skip.
      </p>
    </div>
  )
}
