use anyhow::Result;
use clap::Parser;
use dotenvy::dotenv;
use metrics_exporter_prometheus::PrometheusBuilder;
use tokio::signal;
use tracing::{info, error, warn};
use tracing_subscriber::{EnvFilter, fmt, prelude::*};

mod config;
mod model;
mod ws_client;
mod buffer;
mod db_sink;

use config::Config;
use ws_client::WebSocketClient;
use buffer::BatchProcessor;
use db_sink::DatabaseSink;

#[derive(Parser)]
#[command(name = "ws_recorder")]
#[command(about = "High-performance WebSocket trade recorder for TimescaleDB")]
struct Args {
    #[arg(short, long, default_value = "config.toml")]
    config: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    // Load environment variables
    dotenv().ok();
    
    // Initialize tracing
    init_tracing()?;
    
    // Parse command line arguments
    let args = Args::parse();
    
    // Load configuration
    let config = Config::from_file(&args.config)
        .unwrap_or_else(|e| {
            warn!("Failed to load config from {}: {}. Using defaults.", args.config, e);
            Config::default()
        });
    
    info!("Starting ws_recorder with config: {:?}", config);
    
    // Initialize metrics exporter
    let metrics_addr: std::net::SocketAddr = ([0, 0, 0, 0], config.metrics.port).into();
    PrometheusBuilder::new()
        .with_http_listener(metrics_addr)
        .install()
        .expect("Failed to install Prometheus metrics exporter");
    
    info!("Metrics server listening on http://0.0.0.0:{}/metrics", config.metrics.port);
    
    // Create channels for communication between components
    let (trade_tx, trade_rx) = tokio::sync::mpsc::unbounded_channel();
    let (batch_tx, batch_rx) = tokio::sync::mpsc::unbounded_channel();
    
    // Start database sink
    let db_sink = DatabaseSink::new(&config.db.uri, batch_rx).await?;
    let db_handle = tokio::spawn(async move {
        if let Err(e) = db_sink.run().await {
            error!("Database sink error: {}", e);
        }
    });
    
    // Start batch processor
    let batch_processor = BatchProcessor::new(
        config.batch.max_rows,
        config.batch.max_ms,
        trade_rx,
        batch_tx,
    );
    let batch_handle = tokio::spawn(async move {
        batch_processor.run().await;
    });
    
    // Start WebSocket client
    let ws_client = WebSocketClient::new(config.exchange.clone(), trade_tx);
    let ws_handle = tokio::spawn(async move {
        if let Err(e) = ws_client.run().await {
            error!("WebSocket client error: {}", e);
        }
    });
    
    info!("All components started successfully");
    
    // Wait for shutdown signal
    match signal::ctrl_c().await {
        Ok(()) => {
            info!("Received SIGINT, initiating graceful shutdown...");
        }
        Err(err) => {
            error!("Unable to listen for shutdown signal: {}", err);
        }
    }
    
    // Graceful shutdown
    info!("Shutting down...");
    
    // Cancel all tasks
    ws_handle.abort();
    batch_handle.abort();
    db_handle.abort();
    
    // Wait a bit for graceful shutdown
    tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
    
    info!("Shutdown complete");
    Ok(())
}

fn init_tracing() -> Result<()> {
    let env_filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));
    
    tracing_subscriber::registry()
        .with(
            fmt::layer()
                .with_target(true)
                .with_level(true)
                .with_thread_ids(true)
                .json()
        )
        .with(env_filter)
        .try_init()?;
    
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::*;

    #[test]
    fn test_kraken_trade_parsing() {
        let kraken_trade = KrakenTradeData {
            price: "50000.0".to_string(),
            volume: "0.1".to_string(),
            time: "1234567890.123".to_string(),
            side: "b".to_string(),
            order_type: "market".to_string(),
            misc: "".to_string(),
        };
        
        let trade = Trade::from_kraken_trade(&kraken_trade, "BTC/USDT", "kraken").unwrap();
        
        assert_eq!(trade.symbol, "BTC/USDT");
        assert_eq!(trade.venue, "kraken");
        assert!(matches!(trade.side, TradeSide::Buy));
        assert!(trade.price > rust_decimal::Decimal::ZERO);
        assert!(trade.qty > rust_decimal::Decimal::ZERO);
    }

    #[test]
    fn test_invalid_price_rejection() {
        let kraken_trade = KrakenTradeData {
            price: "-50000.0".to_string(),
            volume: "0.1".to_string(),
            time: "1234567890.123".to_string(),
            side: "b".to_string(),
            order_type: "market".to_string(),
            misc: "".to_string(),
        };
        
        let result = Trade::from_kraken_trade(&kraken_trade, "BTC/USDT", "kraken");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_quantity_rejection() {
        let kraken_trade = KrakenTradeData {
            price: "50000.0".to_string(),
            volume: "0".to_string(),
            time: "1234567890.123".to_string(),
            side: "b".to_string(),
            order_type: "market".to_string(),
            misc: "".to_string(),
        };
        
        let result = Trade::from_kraken_trade(&kraken_trade, "BTC/USDT", "kraken");
        assert!(result.is_err());
    }
}