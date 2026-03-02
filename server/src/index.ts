import { createApp } from "./app";
import { startDiscoveryRunPruner } from "./polymarket/services/discoveryRunService";

function parseBooleanEnv(name: string, fallback = false): boolean {
  const value = process.env[name];
  if (value === undefined) {
    return fallback;
  }

  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

const PORT = Number(process.env.PORT ?? 4000);
const app = createApp();

let prunerStop: (() => void) | null = null;
if (parseBooleanEnv("DISCOVERY_RUN_PRUNER_ENABLED", false)) {
  prunerStop = startDiscoveryRunPruner().stop;
}

const server = app.listen(PORT, () => {
  console.log(`🚀 Server running on http://localhost:${PORT}`);
  if (prunerStop) {
    console.log("🧹 Discovery run pruner enabled");
  }
});

const shutdown = async () => {
  if (prunerStop) {
    prunerStop();
    prunerStop = null;
  }

  server.close(() => {
    process.exit(0);
  });
};

process.once("SIGINT", shutdown);
process.once("SIGTERM", shutdown);
