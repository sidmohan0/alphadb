import { Pool } from "pg";

let pool: Pool | null = null;

export function getPgConnectionString(): string {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("DATABASE_URL is required for discovery run persistence");
  }

  return databaseUrl;
}

export function getPgPool(): Pool {
  if (!pool) {
    pool = new Pool({ connectionString: getPgConnectionString(), max: 5 });
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
