import { ensureDiscoverySchema } from "./discoverySchema";

async function applySqlMigration(): Promise<void> {
  const result = await ensureDiscoverySchema({ closePoolAfter: true });

  if (result.applied) {
    console.log(`Discovery run schema upgraded from v${result.from} to v${result.to}.`);
  } else {
    console.log(`Discovery run schema already at v${result.to}; no migration needed.`);
  }
}

applySqlMigration().catch((error) => {
  console.error("Failed to apply discovery run schema", error);
  process.exit(1);
});
