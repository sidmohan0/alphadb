use anyhow::{Context, Result};
use std::fs;
use trading_common::StrategyConfig;

#[derive(Clone)]
pub struct AgentConfig {
    pub strategy_path: String,
    pub socket: String,
    pub cycle_secs: u64,
}

pub fn load_config() -> AgentConfig {
    let strategy = std::env::var("TRADING_STRATEGY_CONFIG")
        .unwrap_or_else(|_| "config/strategies/mean-reversion-funding.yaml".to_string());
    let socket = std::env::var("TRADING_GATE_SOCKET").unwrap_or_else(|_| "/tmp/trading-gate.sock".to_string());
    let cycle_secs = std::env::var("TRADING_AGENT_CYCLE_SECONDS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(2);
    AgentConfig {
        strategy_path: strategy,
        socket,
        cycle_secs,
    }
}

pub fn load_strategy_config(path: &str) -> Result<StrategyConfig> {
    let data = fs::read_to_string(path).with_context(|| format!("read strategy config {path}"))?;
    let cfg: StrategyConfig = serde_yaml::from_str(&data)?;
    Ok(cfg)
}

pub fn current_product(default: &str) -> String {
    std::env::var("TRADING_AGENT_PRODUCT")
        .or_else(|_| std::env::var("TRADING_GATE_PRODUCT"))
        .unwrap_or_else(|_| default.to_string())
}
