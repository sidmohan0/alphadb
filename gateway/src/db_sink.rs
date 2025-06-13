use crate::model::Trade;
use anyhow::{Result, anyhow};
use std::time::Instant;
use tokio_postgres::{Client, NoTls};
use tracing::{info, error, warn, debug};

pub struct DatabaseSink {
    client: Client,
    batch_receiver: tokio::sync::mpsc::UnboundedReceiver<Vec<Trade>>,
}

impl DatabaseSink {
    pub async fn new(
        database_uri: &str,
        batch_receiver: tokio::sync::mpsc::UnboundedReceiver<Vec<Trade>>,
    ) -> Result<Self> {
        info!("Connecting to database: {}", database_uri);
        
        let (client, connection) = tokio_postgres::connect(database_uri, NoTls).await?;
        
        // Spawn the connection handler
        tokio::spawn(async move {
            if let Err(e) = connection.await {
                error!("Database connection error: {}", e);
            }
        });

        // Ensure the trades table exists
        Self::ensure_schema(&client).await?;
        
        Ok(Self {
            client,
            batch_receiver,
        })
    }

    async fn ensure_schema(client: &Client) -> Result<()> {
        info!("Ensuring trades table schema exists");
        
        let schema_sql = r#"
            CREATE TABLE IF NOT EXISTS trades (
                ts_exchange   TIMESTAMPTZ NOT NULL,
                ts_ingest     TIMESTAMPTZ NOT NULL DEFAULT now(),
                venue         TEXT        NOT NULL,
                symbol        TEXT        NOT NULL,
                side          TEXT        NOT NULL CHECK (side IN ('buy','sell')),
                price         DOUBLE PRECISION NOT NULL,
                qty           DOUBLE PRECISION NOT NULL,
                PRIMARY KEY   (ts_exchange, venue, symbol, side)
            );
        "#;
        
        client.execute(schema_sql, &[]).await?;
        
        // Create hypertable if TimescaleDB is available
        let hypertable_sql = "SELECT create_hypertable('trades','ts_exchange', if_not_exists=>true);";
        match client.execute(hypertable_sql, &[]).await {
            Ok(_) => info!("Trades hypertable created/verified"),
            Err(e) => warn!("Could not create hypertable (TimescaleDB may not be available): {}", e),
        }
        
        // Create index
        let index_sql = "CREATE INDEX IF NOT EXISTS trades_symbol_time ON trades (symbol, ts_exchange DESC);";
        client.execute(index_sql, &[]).await?;
        
        info!("Database schema ready");
        Ok(())
    }

    pub async fn run(mut self) -> Result<()> {
        info!("Database sink started, waiting for trade batches");
        
        while let Some(trades) = self.batch_receiver.recv().await {
            if let Err(e) = self.insert_trades(trades).await {
                error!("Failed to insert trades: {}", e);
                // Continue processing other batches even if one fails
            }
        }
        
        info!("Database sink shutting down");
        Ok(())
    }

    async fn insert_trades(&self, trades: Vec<Trade>) -> Result<()> {
        if trades.is_empty() {
            return Ok(());
        }

        let start_time = Instant::now();
        let trade_count = trades.len();
        
        debug!("Inserting {} trades", trade_count);

        // Use prepared statement with batch execution for performance
        let insert_sql = r#"
            INSERT INTO trades (ts_exchange, ts_ingest, venue, symbol, side, price, qty)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (ts_exchange, venue, symbol, side) 
            DO NOTHING
        "#;

        let stmt = self.client.prepare(insert_sql).await?;

        for trade in trades {
            let price_f64: f64 = trade.price.try_into()
                .map_err(|_| anyhow!("Price conversion error"))?;
            let qty_f64: f64 = trade.qty.try_into()
                .map_err(|_| anyhow!("Quantity conversion error"))?;

            self.client.execute(&stmt, &[
                &trade.ts_exchange,
                &trade.ts_ingest,
                &trade.venue,
                &trade.symbol,
                &trade.side.to_string(),
                &price_f64,
                &qty_f64,
            ]).await?;
        }
        
        let duration = start_time.elapsed();
        let duration_ms = duration.as_millis() as f64;
        
        metrics::histogram!("db_insert_ms_bucket").record(duration_ms);
        info!("Inserted {} trades in {:.2}ms", trade_count, duration_ms);
        
        Ok(())
    }
}

// Alternative implementation using individual INSERTs with ON CONFLICT
pub async fn insert_trades_with_upsert(
    client: &Client,
    trades: Vec<Trade>,
) -> Result<()> {
    if trades.is_empty() {
        return Ok(());
    }

    let start_time = Instant::now();
    let trade_count = trades.len();
    
    debug!("Inserting {} trades with upsert", trade_count);

    let insert_sql = r#"
        INSERT INTO trades (ts_exchange, ts_ingest, venue, symbol, side, price, qty)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (ts_exchange, venue, symbol, side) 
        DO UPDATE SET 
            ts_ingest = EXCLUDED.ts_ingest,
            price = EXCLUDED.price,
            qty = EXCLUDED.qty
    "#;

    let stmt = client.prepare(insert_sql).await?;

    for trade in trades {
        let price_f64: f64 = trade.price.try_into()
            .map_err(|_| anyhow!("Price conversion error"))?;
        let qty_f64: f64 = trade.qty.try_into()
            .map_err(|_| anyhow!("Quantity conversion error"))?;

        client.execute(&stmt, &[
            &trade.ts_exchange,
            &trade.ts_ingest,
            &trade.venue,
            &trade.symbol,
            &trade.side.to_string(),
            &price_f64,
            &qty_f64,
        ]).await?;
    }

    let duration = start_time.elapsed();
    let duration_ms = duration.as_millis() as f64;
    
    metrics::histogram!("db_insert_ms_bucket").record(duration_ms);
    info!("Inserted {} trades with upsert in {:.2}ms", trade_count, duration_ms);
    
    Ok(())
}