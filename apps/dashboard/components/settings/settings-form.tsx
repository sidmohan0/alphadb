"use client"

import { useState } from "react"
import { mockSettings, TradingSettings } from "@/lib/strategy-data"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"

export function SettingsForm() {
  const [settings, setSettings] = useState<TradingSettings>(mockSettings)
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-8 max-w-2xl">
      <section>
        <h2 className="text-sm font-medium text-foreground mb-4">Position Limits</h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm text-foreground">Max Position Size</label>
              <p className="text-xs text-muted-foreground">Maximum contracts per position</p>
            </div>
            <input
              type="number"
              value={settings.maxPositionSize}
              onChange={(e) => setSettings({ ...settings, maxPositionSize: parseInt(e.target.value) || 0 })}
              className="w-24 h-9 px-3 bg-muted border border-border rounded-md text-sm font-mono text-right"
            />
          </div>
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm text-foreground">Max Daily Loss</label>
              <p className="text-xs text-muted-foreground">Stop trading if daily loss exceeds this</p>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-sm text-muted-foreground">$</span>
              <input
                type="number"
                value={settings.maxDailyLoss}
                onChange={(e) => setSettings({ ...settings, maxDailyLoss: parseInt(e.target.value) || 0 })}
                className="w-24 h-9 px-3 bg-muted border border-border rounded-md text-sm font-mono text-right"
              />
            </div>
          </div>
        </div>
      </section>

      <Separator />

      <section>
        <h2 className="text-sm font-medium text-foreground mb-4">Agent Behavior</h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm text-foreground">Min Confidence Threshold</label>
              <p className="text-xs text-muted-foreground">Agent won&apos;t trade below this confidence</p>
            </div>
            <input
              type="number"
              step="0.1"
              min="0"
              max="1"
              value={settings.minConfidenceThreshold}
              onChange={(e) => setSettings({ ...settings, minConfidenceThreshold: parseFloat(e.target.value) || 0 })}
              className="w-24 h-9 px-3 bg-muted border border-border rounded-md text-sm font-mono text-right"
            />
          </div>
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm text-foreground">Default Cycle Duration</label>
              <p className="text-xs text-muted-foreground">Minutes between decision cycles</p>
            </div>
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={settings.defaultCycleMinutes}
                onChange={(e) => setSettings({ ...settings, defaultCycleMinutes: parseInt(e.target.value) || 15 })}
                className="w-24 h-9 px-3 bg-muted border border-border rounded-md text-sm font-mono text-right"
              />
              <span className="text-sm text-muted-foreground">min</span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm text-foreground">Auto-restart on Error</label>
              <p className="text-xs text-muted-foreground">Automatically restart stopped strategies</p>
            </div>
            <button
              onClick={() => setSettings({ ...settings, autoRestart: !settings.autoRestart })}
              className={`w-12 h-6 rounded-full transition-colors ${
                settings.autoRestart ? "bg-primary" : "bg-muted"
              }`}
            >
              <div
                className={`w-5 h-5 bg-white rounded-full shadow transition-transform ${
                  settings.autoRestart ? "translate-x-6" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>
        </div>
      </section>

      <Separator />

      <section>
        <h2 className="text-sm font-medium text-foreground mb-4">Notifications</h2>
        <div className="space-y-3">
          {[
            { key: "onTrade" as const, label: "On Trade", desc: "Notify when a trade is executed" },
            { key: "onCycle" as const, label: "On Cycle", desc: "Notify at each decision cycle" },
            { key: "onError" as const, label: "On Error", desc: "Notify when an error occurs" },
          ].map((item) => (
            <div key={item.key} className="flex items-center justify-between">
              <div>
                <label className="text-sm text-foreground">{item.label}</label>
                <p className="text-xs text-muted-foreground">{item.desc}</p>
              </div>
              <button
                onClick={() =>
                  setSettings({
                    ...settings,
                    notifications: {
                      ...settings.notifications,
                      [item.key]: !settings.notifications[item.key],
                    },
                  })
                }
                className={`w-12 h-6 rounded-full transition-colors ${
                  settings.notifications[item.key] ? "bg-primary" : "bg-muted"
                }`}
              >
                <div
                  className={`w-5 h-5 bg-white rounded-full shadow transition-transform ${
                    settings.notifications[item.key] ? "translate-x-6" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>
          ))}
        </div>
      </section>

      <div className="pt-4">
        <Button onClick={handleSave} className="w-full sm:w-auto">
          {saved ? "Saved!" : "Save Settings"}
        </Button>
      </div>
    </div>
  )
}
