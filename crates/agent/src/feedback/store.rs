use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::Write;

#[derive(Debug, Serialize, Deserialize)]
pub struct Loop1Record {
    pub timestamp: String,
    pub slug: String,
    pub strategy: String,
    pub symbol: String,
    pub pnl: f64,
    pub mae: f64,
    pub mfe: f64,
    pub holdings_minutes: i64,
    pub checks: Vec<trading_common::CheckResult>,
}

pub fn append_event(event: &Loop1Record) -> Result<()> {
    fs::create_dir_all("data")?;
    let mut file = OpenOptions::new().create(true).append(true).open("data/events.log")?;
    let line = serde_json::to_string(event)?;
    writeln!(file, "{line}")?;
    Ok(())
}
