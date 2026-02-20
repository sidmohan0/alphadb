use chrono::Utc;
use trading_common::{Side, StrategyConfig};

#[derive(Debug, Clone)]
pub struct Signal {
    pub symbol: String,
    pub side: Side,
    pub strength: f64,
    pub planned_entry: f64,
    pub planned_stop: f64,
    pub thesis_slug: String,
    pub funding_zscore: f64,
}

pub struct StrategyContext {
    pub symbol: String,
    pub price: f64,
    pub funding_zscore: f64,
    pub hour: u32,
    pub _product: String,
}

#[derive(Debug, Clone)]
pub struct StrategyPolicy {
    pub name: String,
    pub _params: StrategyConfig,
    pub cash_per_trade: f64,
}

impl StrategyPolicy {
    pub fn from_config(cfg: StrategyConfig, account_value: f64) -> Self {
        let size = account_value * 0.01 * cfg.capital_allocation.max(0.0).min(0.5);
        Self {
            name: cfg.name.clone(),
            _params: cfg,
            cash_per_trade: size.max(10.0),
        }
    }

    pub fn generate(&self, ctx: &StrategyContext) -> Option<Signal> {
        if ctx.funding_zscore <= -2.0 {
            let entry = ctx.price * 0.999;
            Some(Signal {
                symbol: ctx.symbol.clone(),
                side: Side::Buy,
                strength: (-ctx.funding_zscore) / 3.0,
                planned_entry: entry,
                planned_stop: entry * 0.985,
                funding_zscore: ctx.funding_zscore,
                thesis_slug: format!(
                    "{}-{}-{}-funding-reversion",
                    Utc::now().format("%Y-%m-%d"),
                    ctx.side_hint(),
                    ctx.symbol.to_lowercase()
                ),
            })
        } else if ctx.funding_zscore >= 2.0 {
            let entry = ctx.price * 1.001;
            Some(Signal {
                symbol: ctx.symbol.clone(),
                side: Side::Sell,
                strength: ctx.funding_zscore / 3.0,
                planned_entry: entry,
                planned_stop: entry * 1.015,
                funding_zscore: ctx.funding_zscore,
                thesis_slug: format!(
                    "{}-{}-{}-funding-reversion",
                    Utc::now().format("%Y-%m-%d"),
                    ctx.side_hint(),
                    ctx.symbol.to_lowercase()
                ),
            })
        } else {
            None
        }
    }

    pub fn size_for(&self, entry_price: f64) -> f64 {
        if entry_price <= 0.0 {
            return 0.0;
        }
        self.cash_per_trade / entry_price
    }
}

impl StrategyContext {
    fn side_hint(&self) -> &'static str {
        if self.hour >= 12 { "long" } else { "short" }
    }
}
