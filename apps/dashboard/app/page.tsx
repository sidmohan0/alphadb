import { AppShell } from "@/components/app-shell"
import { StrategyOperatorLedger } from "@/components/live/strategy-operator-ledger"

export default function HomePage() {
  return (
    <AppShell showStrategySelector={false}>
      <StrategyOperatorLedger />
    </AppShell>
  )
}
