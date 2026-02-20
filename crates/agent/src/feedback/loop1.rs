use anyhow::Result;
use std::collections::HashSet;

use trading_common::Fill;

use super::store::{append_event, Loop1Record};

#[derive(Default)]
pub struct Loop1 {
    seen_orders: HashSet<String>,
}

impl Loop1 {
    pub fn on_fills(&mut self, fills: &[Fill]) -> Result<()> {
        for fill in fills.iter().filter(|f| !f.is_entry) {
            if !self.seen_orders.insert(fill.order_id.clone()) {
                continue;
            }

            // Real compute is intentionally minimal in bootstrap.
            let record = Loop1Record {
                timestamp: fill.filled_at.to_rfc3339(),
                slug: fill.order_id.clone(),
                strategy: fill.strategy.clone(),
                symbol: fill.symbol.clone(),
                pnl: 0.0,
                mae: 0.0,
                mfe: 0.0,
                holdings_minutes: 0,
                checks: Vec::new(),
            };

            append_event(&record)?;
        }
        Ok(())
    }
}
