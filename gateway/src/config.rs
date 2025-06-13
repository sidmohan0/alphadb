use serde::{Deserialize, Serialize};
use std::path::Path;
use anyhow::Result;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Config {
    pub db: DatabaseConfig,
    pub exchange: ExchangeConfig,
    pub batch: BatchConfig,
    pub metrics: MetricsConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DatabaseConfig {
    pub uri: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ExchangeConfig {
    pub venue: String,
    pub pairs: Vec<String>,
    pub ws_url: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BatchConfig {
    pub max_rows: usize,
    pub max_ms: u64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MetricsConfig {
    pub port: u16,
}

impl Config {
    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        let config: Config = toml::from_str(&content)?;
        Ok(config)
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            db: DatabaseConfig {
                uri: "postgresql://trader:s3cr3t@localhost:5432/market".to_string(),
            },
            exchange: ExchangeConfig {
                venue: "kraken".to_string(),
                pairs: vec!["BTC/USDT".to_string(), "ETH/USDT".to_string()],
                ws_url: "wss://ws.kraken.com".to_string(),
            },
            batch: BatchConfig {
                max_rows: 5000,
                max_ms: 500,
            },
            metrics: MetricsConfig {
                port: 9187,
            },
        }
    }
}