import { Pool, type PoolConfig } from "pg";

let pool: Pool | null = null;

function parseIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) && Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function getPgConnectionString(): string {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("DATABASE_URL is required for Postgres-backed persistence");
  }

  return databaseUrl;
}

export function getPgPool(): Pool {
  if (!pool) {
    const poolConfig: PoolConfig = {
      connectionString: getPgConnectionString(),
      max: parseIntEnv("PG_POOL_MAX", 5),
      idleTimeoutMillis: parseIntEnv("PG_POOL_IDLE_TIMEOUT_MS", 30000),
      connectionTimeoutMillis: parseIntEnv("PG_POOL_CONNECT_TIMEOUT_MS", 2000),
    };

    pool = new Pool(poolConfig);
  }

  return pool;
}

export async function closePgPool(): Promise<void> {
  if (!pool) {
    return;
  }

  await pool.end();
  pool = null;
}
