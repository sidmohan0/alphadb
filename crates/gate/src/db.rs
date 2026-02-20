use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use rusqlite::{params, Connection};
use trading_common::{Fill, Order, Side};

pub struct Db {
    conn: Connection,
}

impl Db {
    pub fn new(path: &str) -> Result<Self> {
        let conn = Connection::open(path).context("open sqlite db")?;
        let db = Self { conn };
        db.init()?;
        Ok(db)
    }

    fn init(&self) -> Result<()> {
        self.conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS positions (
                order_id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                stop_price REAL,
                thesis_slug TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL,
                filled_at TEXT NOT NULL,
                strategy TEXT NOT NULL,
                thesis_slug TEXT NOT NULL,
                is_entry INTEGER NOT NULL
            );
            "#,
        )
        .context("initialize sqlite schema")?;
        Ok(())
    }

    pub fn upsert_position(&self, order: &Order, entry_price: f64, order_time: DateTime<Utc>) -> Result<()> {
        self.conn
            .execute(
                "INSERT OR REPLACE INTO positions (order_id, strategy, symbol, side, size, entry_price, entry_time, stop_price, thesis_slug) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
                params![
                    order.id,
                    order.strategy,
                    order.symbol,
                    order.side.as_str(),
                    order.size,
                    entry_price,
                    order_time.to_rfc3339(),
                    order.stop_price,
                    order.thesis_slug
                ],
            )
            .context("write position")?;
        Ok(())
    }

    pub fn remove_position(&self, order_id: &str) -> Result<()> {
        self.conn
            .execute(
                "DELETE FROM positions WHERE order_id = ?1",
                params![order_id],
            )
            .context("remove position")?;
        Ok(())
    }
    pub fn insert_fill(&self, fill: &Fill) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO fills (order_id, symbol, side, size, price, fee, filled_at, strategy, thesis_slug, is_entry) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    fill.order_id,
                    fill.symbol,
                    fill.side.as_str(),
                    fill.size,
                    fill.price,
                    fill.fee,
                    fill.filled_at.to_rfc3339(),
                    fill.strategy,
                    fill.thesis_slug,
                    if fill.is_entry { 1 } else { 0 }
                ],
            )
            .context("insert fill")?;
        Ok(())
    }

    pub fn fills_since(&self, since: DateTime<Utc>) -> Result<Vec<Fill>> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT order_id, symbol, side, size, price, fee, filled_at, strategy, thesis_slug, is_entry \
                 FROM fills WHERE filled_at >= ?1 ORDER BY filled_at DESC",
            )
            .context("prepare fills query")?;
        let rows = stmt
            .query_map(params![since.to_rfc3339()], |r| {
                Ok(Fill {
                    order_id: r.get(0)?,
                    symbol: r.get(1)?,
                    side: match r.get::<_, String>(2)?.as_str() {
                        "buy" => Side::Buy,
                        _ => Side::Sell,
                    },
                    size: r.get(3)?,
                    price: r.get(4)?,
                    fee: r.get(5)?,
                    filled_at: r.get::<_, String>(6)?.parse::<chrono::DateTime<Utc>>().unwrap_or_else(|_| Utc::now()),
                    strategy: r.get(7)?,
                    thesis_slug: r.get(8)?,
                    is_entry: r.get::<_, i64>(9)? == 1,
                })
            })
            .context("query fills")?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row.context("read fill row")?);
        }
        Ok(out)
    }
}
