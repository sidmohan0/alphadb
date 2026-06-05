import { AppShell } from "@/components/app-shell"
import { StrategiesTable } from "@/components/strategies/strategies-table"

export default function StrategiesPage() {
  return (
    <AppShell>
      <div className="p-6 space-y-6">
        <h1 className="text-lg font-semibold text-foreground">Strategies</h1>
        <StrategiesTable />
      </div>
    </AppShell>
  )
}
