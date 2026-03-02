import { readFileSync } from "fs";
import { resolve } from "path";

import { closePgPool, getPgPool } from "../infra/db/postgres";

async function applySqlMigration(): Promise<void> {
  const pool = getPgPool();
  const sqlPath = resolve(__dirname, "../infra/db/schemas.sql");
  const sql = readFileSync(sqlPath, "utf8");

  try {
    await pool.query(sql);
    console.log("Discovery run schema applied successfully.");
  } finally {
    await closePgPool();
  }
}

applySqlMigration().catch((error) => {
  console.error("Failed to apply discovery run schema", error);
  process.exit(1);
});
