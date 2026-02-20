use chrono::Utc;
use std::collections::HashMap;

use trading_common::{Decimal, Fill, Order, PortfolioState, Side};

#[derive(Debug, Clone)]
pub struct Position {
    pub id: String,
    pub strategy: String,
    pub symbol: String,
    pub side: Side,
    pub size: Decimal,
    pub entry_price: Decimal,
    pub entry_time: chrono::DateTime<Utc>,
    pub thesis_slug: String,
    pub stop_price: Option<Decimal>,
}

#[derive(Debug)]
pub struct GateState {
    pub account_value: Decimal,
    pub cash: Decimal,
    pub equity_peak: Decimal,
    pub manual_halt: bool,
    pub orders: HashMap<String, Order>,
    pub positions: HashMap<String, Position>,
    pub fills: Vec<Fill>,
    pub can_trade: bool,
}

impl Default for GateState {
    fn default() -> Self {
        Self {
            account_value: 10_000.0,
            cash: 10_000.0,
            equity_peak: 10_000.0,
            manual_halt: false,
            orders: HashMap::new(),
            positions: HashMap::new(),
            fills: Vec::new(),
            can_trade: true,
        }
    }
}

impl GateState {
    pub fn portfolio_state(&self) -> PortfolioState {
        let exposure: Decimal = self.positions.values().map(|p| p.entry_price * p.size).sum();

        let daily: Decimal = self.fills.iter().filter(|f| f.filled_at.date_naive() == Utc::now().date_naive()).map(|f| {
            if f.is_entry { 0.0 } else { f.size * f.price / 1000.0 }
        }).sum();
        let weekly = daily;
        let drawdown = if self.equity_peak > 0.0 {
            (self.equity_peak - self.account_value) / self.equity_peak
        } else {
            0.0
        };

        PortfolioState {
            account_value: self.account_value,
            available_cash: self.cash,
            total_exposure: exposure,
            open_position_count: self.positions.len() as u32,
            daily_pnl: daily,
            weekly_pnl: weekly,
            drawdown_from_peak: drawdown,
            updated_at: Utc::now(),
        }
    }

    pub fn add_fill(&mut self, fill: Fill) {
        if fill.is_entry {
            self.cash -= fill.price * fill.size + fill.fee;
        } else {
            self.cash += fill.price * fill.size - fill.fee;
        }

        self.fills.push(fill);
        if self.account_value > self.equity_peak {
            self.equity_peak = self.account_value;
        }
    }
}
