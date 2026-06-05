import { AppShell } from "@/components/app-shell"
import { SettingsForm } from "@/components/settings/settings-form"

export default function SettingsPage() {
  return (
    <AppShell>
      <div className="p-6 space-y-6">
        <h1 className="text-lg font-semibold text-foreground">Settings</h1>
        <SettingsForm />
      </div>
    </AppShell>
  )
}
