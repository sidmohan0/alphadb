import { closeRedisClient, getRedisClient } from "./polymarket/infra/cache/redis";
import { closePgPool } from "./polymarket/infra/db/postgres";
import { ensureDiscoverySchema } from "./polymarket/maintenance/discoverySchema";
import { createApp } from "./app";
import { startDiscoveryRunPruner } from "./polymarket/services/discoveryRunService";

function parseBooleanEnv(name: string, fallback = false): boolean {
  const value = process.env[name];
  if (value === undefined) {
    return fallback;
  }

  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

function parseIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

async function verifyRedisConnectivity(): Promise<void> {
  if (!process.env.REDIS_URL) {
    if (!parseBooleanEnv("DISCOVERY_RUN_ALLOW_IN_MEMORY_CACHE", false)) {
      throw new Error("REDIS_URL is required for discovery cache/locks unless DISCOVERY_RUN_ALLOW_IN_MEMORY_CACHE=1");
    }

    return;
  }

  const redis = getRedisClient();
  await redis.ping();
  console.log("✅ Redis connectivity check passed");
}

const PORT = parseIntEnv("PORT", 4000);
const app = createApp();

let prunerStop: (() => void) | null = null;
let isShuttingDown = false;
let server: ReturnType<typeof app.listen>;

function stopPruner(): void {
  if (prunerStop) {
    prunerStop();
    prunerStop = null;
  }
}

function handleShutdownError(error: unknown): void {
  console.error("Shutdown failed", error);
  process.exit(1);
}

async function closeResources(): Promise<void> {
  await Promise.allSettled([closeRedisClient(), closePgPool()]);
}

async function shutdown(): Promise<void> {
  if (isShuttingDown) {
    return;
  }
  isShuttingDown = true;

  try {
    stopPruner();

    if (server) {
      await new Promise<void>((resolve, reject) => {
        server.close((error?: Error) => {
          if (error) {
            reject(error);
            return;
          }

          resolve();
        });
      });
    }

    await closeResources();
    process.exit(0);
  } catch (error) {
    handleShutdownError(error);
  }
}

async function bootstrap(): Promise<void> {
  await verifyRedisConnectivity();

  if (parseBooleanEnv("DISCOVERY_REQUIRE_SCHEMA", false)) {
    const result = await ensureDiscoverySchema({ closePoolAfter: false });
    if (result.applied) {
      console.log(`Schema state: updated v${result.from} -> v${result.to}`);
    }
  }

  if (parseBooleanEnv("DISCOVERY_RUN_PRUNER_ENABLED", false)) {
    prunerStop = startDiscoveryRunPruner().stop;
  }

  server = app.listen(PORT, () => {
    console.log(`🚀 Server running on http://localhost:${PORT}`);
    if (prunerStop) {
      console.log("🧹 Discovery run pruner enabled");
    }
  });
}

bootstrap().catch((error) => {
  console.error("Failed to bootstrap server", error);
  process.exit(1);
});

process.once("SIGINT", () => {
  void shutdown();
});
process.once("SIGTERM", () => {
  void shutdown();
});
