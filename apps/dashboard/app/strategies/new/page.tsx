"use client"

import { useState } from "react"
import Link from "next/link"
import { AppShell } from "@/components/app-shell"
import { Button } from "@/components/ui/button"
import { apiPost } from "@/lib/alphadb-api"
import { ArrowLeft, FlaskConical, Save, Wand2 } from "lucide-react"

interface CompileResult {
  status: "supported" | "needs_confirmation" | "unsupported"
  title: string
  selected_template: string | null
  confidence: number
  spec: Record<string, unknown> | null
  missing_fields: string[]
  questions: string[]
  unsupported_reasons: string[]
  closest_templates: string[]
  missing_capabilities: string[]
  lab_entry?: Record<string, unknown>
}

interface SaveResult {
  strategy?: Record<string, unknown> | null
  lab_entry?: Record<string, unknown>
  routed_to_lab?: boolean
  compile?: CompileResult
}

const exampleBrief =
  "Use the BTC 15m model at minute 12. Trade the best side when fair-value edge is above 2%, max $5 per order."

export default function StrategyStudioPage() {
  const [title, setTitle] = useState("BTC 15m fair-value edge")
  const [brief, setBrief] = useState(exampleBrief)
  const [compile, setCompile] = useState<CompileResult | null>(null)
  const [saved, setSaved] = useState<SaveResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const compileBrief = async () => {
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      setCompile(await apiPost<CompileResult>("/strategies/compile", { title, brief }))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compile failed")
    } finally {
      setBusy(false)
    }
  }

  const saveDraft = async () => {
    setBusy(true)
    setError(null)
    try {
      const payload = compile?.spec ? { name: title, brief, spec: compile.spec } : { name: title, brief }
      setSaved(await apiPost<SaveResult>("/strategies", payload))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed")
    } finally {
      setBusy(false)
    }
  }

  const routeToLab = async () => {
    setBusy(true)
    setError(null)
    try {
      setCompile(
        await apiPost<CompileResult>("/strategies/compile", {
          title,
          brief,
          route_unsupported_to_lab: true,
        })
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lab routing failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <AppShell>
      <div className="p-6 space-y-5 max-w-6xl">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link href="/strategies">
              <Button variant="ghost" size="icon-sm">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
            <div>
              <h1 className="text-lg font-semibold">Strategy Studio</h1>
              <p className="text-sm text-muted-foreground">Brief to JSON Strategy Spec</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={compileBrief} disabled={busy || !brief.trim()}>
              <Wand2 className="h-4 w-4" />
              Compile
            </Button>
            <Button size="sm" onClick={saveDraft} disabled={busy || !brief.trim()}>
              <Save className="h-4 w-4" />
              Save
            </Button>
          </div>
        </div>

        {error && (
          <div className="border border-destructive/40 bg-destructive/10 rounded-lg p-3 text-sm text-destructive">
            {error}
          </div>
        )}
        {saved?.strategy && (
          <div className="border border-success/40 bg-success/10 rounded-lg p-3 text-sm text-success">
            Saved {String(saved.strategy.name || "strategy")}.
          </div>
        )}
        {saved?.routed_to_lab && (
          <div className="border border-warning/40 bg-warning/10 rounded-lg p-3 text-sm text-warning">
            Routed to Lab as {String(saved.lab_entry?.title || "Research Idea")}.
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
          <section className="border border-border rounded-lg bg-card p-4 space-y-4">
            <label className="block text-sm">
              <span className="text-muted-foreground">Title</span>
              <input
                className="mt-2 w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="text-muted-foreground">Strategy Brief</span>
              <textarea
                className="mt-2 min-h-56 w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={brief}
                onChange={(event) => setBrief(event.target.value)}
              />
            </label>
          </section>

          <section className="border border-border rounded-lg bg-card p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium">Compiler Result</h2>
              {compile && <StatusBadge status={compile.status} />}
            </div>

            {compile ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <Value label="Template" value={compile.selected_template || "none"} />
                  <Value label="Confidence" value={`${Math.round(compile.confidence * 100)}%`} />
                </div>
                {!!compile.missing_fields.length && (
                  <ListBlock title="Missing Fields" items={compile.missing_fields} />
                )}
                {!!compile.questions.length && (
                  <ListBlock title="Questions" items={compile.questions} />
                )}
                {!!compile.unsupported_reasons.length && (
                  <ListBlock title="Unsupported" items={compile.unsupported_reasons} />
                )}
                {compile.status === "unsupported" && (
                  <Button variant="outline" size="sm" onClick={routeToLab} disabled={busy}>
                    <FlaskConical className="h-4 w-4" />
                    Save Research Idea
                  </Button>
                )}
                {compile.spec && (
                  <pre className="max-h-80 overflow-auto rounded-md bg-background p-3 text-xs text-muted-foreground">
                    {JSON.stringify(compile.spec, null, 2)}
                  </pre>
                )}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">No compile result yet.</div>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  )
}

function StatusBadge({ status }: { status: CompileResult["status"] }) {
  const className =
    status === "supported"
      ? "text-success border-success/40"
      : status === "unsupported"
        ? "text-destructive border-destructive/40"
        : "text-warning border-warning/40"
  return <span className={`rounded-md border px-2 py-0.5 text-xs ${className}`}>{status}</span>
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-xs">{value}</div>
    </div>
  )
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground mb-2">{title}</div>
      <ul className="space-y-1 text-sm">
        {items.map((item) => (
          <li key={item} className="rounded-md bg-muted px-2 py-1">{item}</li>
        ))}
      </ul>
    </div>
  )
}
