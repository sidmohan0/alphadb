import { existsSync, readFileSync } from "fs";
import { resolve } from "path";

import { closePgPool, getPgPool } from "../../polymarket/infra/db/postgres";

interface MarketStateSchemaOptions {
  targetVersion?: number;
  closePoolAfter?: boolean;
}

const MARKET_STATE_SCHEMA_NAME = "market_user_state_schema";
const MARKET_STATE_SCHEMA_TARGET_VERSION = 1;

function parseIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) && Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function resolveSchemaPath(): string {
  const cwd = process.cwd();
  const projectRelative = resolve(cwd, "apps/api/src/markets/infra/db/userStateSchema.sql");
  const localRelative = resolve(__dirname, "../infra/db/userStateSchema.sql");

  if (existsSync(projectRelative)) {
    return projectRelative;
  }

  return localRelative;
}

export async function ensureMarketStateSchema(
  options: MarketStateSchemaOptions = {},
): Promise<{ applied: boolean; from: number; to: number }> {
  const targetVersion =
    options.targetVersion ?? parseIntEnv("MARKET_STATE_SCHEMA_TARGET_VERSION", MARKET_STATE_SCHEMA_TARGET_VERSION);
  const closePoolAfter = options.closePoolAfter ?? false;
  const pool = getPgPool();

  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS market_state_schema_migrations (
        schema_name TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);

    const versionResult = await pool.query(
      "SELECT version FROM market_state_schema_migrations WHERE schema_name=$1",
      [MARKET_STATE_SCHEMA_NAME],
    );

    const currentVersion =
      versionResult.rowCount && versionResult.rows[0] ? Number(versionResult.rows[0].version) : 0;

    if (currentVersion >= targetVersion) {
      return { applied: false, from: currentVersion, to: currentVersion };
    }

    const sql = readFileSync(resolveSchemaPath(), "utf8");
    await pool.query(sql);

    await pool.query(
      `INSERT INTO market_state_schema_migrations (schema_name, version)
       VALUES ($1, $2)
       ON CONFLICT (schema_name) DO UPDATE SET version = EXCLUDED.version, updated_at = NOW()`,
      [MARKET_STATE_SCHEMA_NAME, targetVersion],
    );

    return { applied: true, from: currentVersion, to: targetVersion };
  } finally {
    if (closePoolAfter) {
      await closePgPool();
    }
  }
}

if (require.main === module) {
  ensureMarketStateSchema({ closePoolAfter: true })
    .then((result) => {
      if (result.applied) {
        console.log(`Market user state schema updated from v${result.from} to v${result.to}`);
      } else {
        console.log(`Market user state schema already at v${result.to}`);
      }

      process.exit(0);
    })
    .catch((error: unknown) => {
      console.error("Failed to ensure market user state schema", error);
      process.exit(1);
    });
}
