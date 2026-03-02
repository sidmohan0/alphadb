import { existsSync, readFileSync } from "fs";
import { resolve } from "path";

import { closePgPool, getPgPool } from "../infra/db/postgres";

interface DiscoverySchemaOptions {
  targetVersion?: number;
  closePoolAfter?: boolean;
}

const DISCOVERY_SCHEMA_NAME = "discovery_runs_schema";

function parseIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) && Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

const DISCOVERY_SCHEMA_TARGET_VERSION = 1;

function resolveSchemaPath(): string {
  const cwd = process.cwd();
  const projectRelative = resolve(cwd, "server/src/polymarket/infra/db/schemas.sql");
  const localRelative = resolve(__dirname, "../infra/db/schemas.sql");

  if (existsSync(projectRelative)) {
    return projectRelative;
  }

  return localRelative;
}

export async function ensureDiscoverySchema(options: DiscoverySchemaOptions = {}): Promise<{ applied: boolean; from: number; to: number }> {
  const targetVersion = options.targetVersion ?? parseIntEnv("DISCOVERY_SCHEMA_TARGET_VERSION", DISCOVERY_SCHEMA_TARGET_VERSION);

  const closePoolAfter = options.closePoolAfter ?? false;
  const pool = getPgPool();

  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS discovery_schema_migrations (
        schema_name TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);

    const versionResult = await pool.query(
      "SELECT version FROM discovery_schema_migrations WHERE schema_name=$1",
      [DISCOVERY_SCHEMA_NAME]
    );

    const currentVersion =
      versionResult.rowCount && versionResult.rows[0] ? Number(versionResult.rows[0].version) : 0;

    if (currentVersion >= targetVersion) {
      return { applied: false, from: currentVersion, to: currentVersion };
    }

    const sqlPath = resolveSchemaPath();
    const sql = readFileSync(sqlPath, "utf8");
    await pool.query(sql);

    await pool.query(
      `INSERT INTO discovery_schema_migrations (schema_name, version)
       VALUES ($1, $2)
       ON CONFLICT (schema_name) DO UPDATE SET version = EXCLUDED.version, updated_at = NOW()`,
      [DISCOVERY_SCHEMA_NAME, targetVersion]
    );

    return { applied: true, from: currentVersion, to: targetVersion };
  } finally {
    if (closePoolAfter) {
      await closePgPool();
    }
  }
}

if (require.main === module) {
  ensureDiscoverySchema({ closePoolAfter: true })
    .then((result) => {
      if (result.applied) {
        console.log(`Discovery schema updated from v${result.from} to v${result.to}`);
      } else {
        console.log(`Discovery schema already at v${result.to}`);
      }

      process.exit(0);
    })
    .catch((error: unknown) => {
      console.error("Failed to ensure discovery schema", error);
      process.exit(1);
    });
}
