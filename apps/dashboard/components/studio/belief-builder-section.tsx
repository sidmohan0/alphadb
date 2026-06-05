"use client"

import { ChevronDown, Brain, Calculator, Cpu, Plus, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { StrategyDraft } from "@/app/strategies/new/page"

interface BeliefBuilderSectionProps {
  isActive: boolean
  onToggle: () => void
  beliefMode: StrategyDraft["beliefMode"]
  inputs: string[]
  rules: StrategyDraft["rules"]
  formula: StrategyDraft["formula"]
  model: StrategyDraft["model"]
  onChange: (updates: Partial<StrategyDraft>) => void
}

const beliefModes = [
  { 
    id: "rules" as const, 
    name: "Rules", 
    description: "Structural filters and price thresholds",
    icon: Brain,
    color: "text-purple-500 bg-purple-500/10"
  },
  { 
    id: "formula" as const, 
    name: "Formula", 
    description: "Fair-value math with editable parameters",
    icon: Calculator,
    color: "text-emerald-500 bg-emerald-500/10"
  },
  { 
    id: "model" as const, 
    name: "Model", 
    description: "ML model from registry with calibration",
    icon: Cpu,
    color: "text-blue-500 bg-blue-500/10"
  },
]

const availableInputs = [
  "Coinbase BTC candles",
  "Kalshi quotes",
  "threshold distance",
  "order book depth",
  "recent volume",
  "funding rate",
  "open interest",
  "time to expiry",
]

export function BeliefBuilderSection({ 
  isActive, 
  onToggle, 
  beliefMode,
  inputs,
  rules,
  formula,
  model,
  onChange 
}: BeliefBuilderSectionProps) {
  const currentMode = beliefModes.find(m => m.id === beliefMode)!
  
  const addInput = (input: string) => {
    if (!inputs.includes(input)) {
      onChange({ inputs: [...inputs, input] })
    }
  }
  
  const removeInput = (input: string) => {
    onChange({ inputs: inputs.filter(i => i !== input) })
  }

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className={cn("h-8 w-8 rounded-full flex items-center justify-center", currentMode.color)}>
            <currentMode.icon className="h-4 w-4" />
          </div>
          <div className="text-left">
            <h3 className="font-medium">Belief Builder</h3>
            <p className="text-sm text-muted-foreground">
              {currentMode.name}: {inputs.length} inputs configured
            </p>
          </div>
        </div>
        <ChevronDown className={cn("h-5 w-5 text-muted-foreground transition-transform", isActive && "rotate-180")} />
      </button>
      
      {isActive && (
        <div className="px-4 pb-4 border-t border-border pt-4 space-y-6">
          {/* Mode Selection */}
          <div>
            <label className="text-sm font-medium mb-3 block">Belief Source</label>
            <div className="grid grid-cols-3 gap-2">
              {beliefModes.map((mode) => (
                <button
                  key={mode.id}
                  onClick={() => onChange({ beliefMode: mode.id })}
                  className={cn(
                    "flex flex-col items-center gap-2 p-4 rounded-lg border transition-colors",
                    beliefMode === mode.id 
                      ? "border-primary bg-primary/5" 
                      : "border-border hover:border-muted-foreground/50"
                  )}
                >
                  <div className={cn("h-10 w-10 rounded-full flex items-center justify-center", mode.color)}>
                    <mode.icon className="h-5 w-5" />
                  </div>
                  <p className="font-medium text-sm">{mode.name}</p>
                  <p className="text-xs text-muted-foreground text-center">{mode.description}</p>
                </button>
              ))}
            </div>
          </div>
          
          {/* Inputs */}
          <div>
            <label className="text-sm font-medium mb-2 block">Data Inputs</label>
            <div className="flex flex-wrap gap-2 mb-3">
              {inputs.map((input) => (
                <span 
                  key={input} 
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-muted rounded-full text-sm"
                >
                  {input}
                  <button 
                    onClick={() => removeInput(input)}
                    className="text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {availableInputs.filter(i => !inputs.includes(i)).map((input) => (
                <button
                  key={input}
                  onClick={() => addInput(input)}
                  className="inline-flex items-center gap-1 px-2.5 py-1 border border-dashed border-border rounded-full text-sm text-muted-foreground hover:text-foreground hover:border-muted-foreground/50 transition-colors"
                >
                  <Plus className="h-3 w-3" />
                  {input}
                </button>
              ))}
            </div>
          </div>
          
          {/* Mode-specific config */}
          {beliefMode === "rules" && (
            <div className="space-y-4 pt-4 border-t border-border">
              <h4 className="text-sm font-medium">Rules Configuration</h4>
              <div className="grid gap-4">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Eligibility Condition</label>
                  <input
                    type="text"
                    value={rules.eligibilityCondition}
                    onChange={(e) => onChange({ rules: { ...rules, eligibilityCondition: e.target.value } })}
                    placeholder="e.g., spread < 5c AND volume > 100"
                    className="w-full bg-muted rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">Price Threshold</label>
                    <input
                      type="number"
                      step="0.01"
                      value={rules.priceThreshold}
                      onChange={(e) => onChange({ rules: { ...rules, priceThreshold: parseFloat(e.target.value) } })}
                      className="w-full bg-muted rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">Side</label>
                    <select
                      value={rules.side}
                      onChange={(e) => onChange({ rules: { ...rules, side: e.target.value as "YES" | "NO" | "best" } })}
                      className="w-full bg-muted rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    >
                      <option value="best">Best Side</option>
                      <option value="YES">YES Only</option>
                      <option value="NO">NO Only</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}
          
          {beliefMode === "formula" && (
            <div className="space-y-4 pt-4 border-t border-border">
              <h4 className="text-sm font-medium">Formula Configuration</h4>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Expression</label>
                <input
                  type="text"
                  value={formula.expression}
                  onChange={(e) => onChange({ formula: { ...formula, expression: e.target.value } })}
                  placeholder="p_yes = ..."
                  className="w-full bg-muted rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Parameters</label>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(formula.parameters).map(([key, value]) => (
                    <div key={key} className="flex items-center gap-2 bg-muted rounded px-3 py-2">
                      <span className="text-sm font-mono text-muted-foreground">{key}:</span>
                      <input
                        type="number"
                        step="0.1"
                        value={value}
                        onChange={(e) => onChange({ 
                          formula: { 
                            ...formula, 
                            parameters: { ...formula.parameters, [key]: parseFloat(e.target.value) } 
                          } 
                        })}
                        className="w-16 bg-transparent text-sm font-mono focus:outline-none"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          
          {beliefMode === "model" && (
            <div className="space-y-4 pt-4 border-t border-border">
              <h4 className="text-sm font-medium">Model Configuration</h4>
              <div className="grid gap-4">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Model Artifact</label>
                  <select
                    value={model.artifactId}
                    onChange={(e) => onChange({ model: { ...model, artifactId: e.target.value } })}
                    className="w-full bg-muted rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="">Select a model...</option>
                    <option value="btc-momentum-v3">btc-momentum-v3 (approved)</option>
                    <option value="btc-vol-predictor-v2">btc-vol-predictor-v2 (approved)</option>
                    <option value="btc-mean-reversion-v1">btc-mean-reversion-v1 (pending)</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Feature Set</label>
                  <select
                    value={model.featureSet}
                    onChange={(e) => onChange({ model: { ...model, featureSet: e.target.value } })}
                    className="w-full bg-muted rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="">Select features...</option>
                    <option value="standard-v2">standard-v2 (price, volume, spread)</option>
                    <option value="extended-v1">extended-v1 (+ funding, OI)</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Calibration</label>
                  <select
                    value={model.calibration}
                    onChange={(e) => onChange({ model: { ...model, calibration: e.target.value } })}
                    className="w-full bg-muted rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="">Select calibration...</option>
                    <option value="isotonic">Isotonic regression</option>
                    <option value="platt">Platt scaling</option>
                    <option value="none">None (raw logits)</option>
                  </select>
                </div>
              </div>
            </div>
          )}
          
          {/* Output contract */}
          <div className="bg-muted rounded-lg p-4">
            <p className="text-xs text-muted-foreground mb-2">Output Contract</p>
            <p className="text-sm font-mono">
              {"{ probability_yes, confidence, feature_version, timestamps, skip_reason? }"}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
