import { LockKeyhole } from "lucide-react"

type LoginPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = (await searchParams) || {}
  const next = firstParam(params.next) || "/"
  const error = firstParam(params.error)

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6">
        <div className="space-y-6 rounded-lg border border-border bg-card p-6">
          <div className="space-y-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-background">
              <LockKeyhole className="h-4 w-4" />
            </div>
            <div>
              <h1 className="text-lg font-semibold">AlphaDB Cockpit</h1>
              <p className="text-sm text-muted-foreground">Enter the operator PIN.</p>
            </div>
          </div>

          <form action="/api/auth/login" method="post" className="space-y-4">
            <input type="hidden" name="next" value={safeNext(next)} />
            <label className="block space-y-2 text-sm">
              <span className="text-muted-foreground">PIN</span>
              <input
                autoComplete="current-password"
                autoFocus
                className="h-10 w-full rounded-md border border-border bg-background px-3 font-mono text-base tracking-[0.18em] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                inputMode="numeric"
                maxLength={4}
                minLength={4}
                name="pin"
                pattern="[0-9]{4}"
                required
                type="password"
              />
            </label>
            {error && (
              <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error === "config"
                  ? "Cockpit auth is not configured correctly."
                  : "PIN rejected."}
              </p>
            )}
            <button
              type="submit"
              className="h-9 w-full rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Continue
            </button>
          </form>
        </div>
      </div>
    </main>
  )
}

function firstParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value
}

function safeNext(value: string) {
  if (!value.startsWith("/") || value.startsWith("//")) return "/"
  return value
}
