use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

pub type Decimal = f64;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Side {
    Buy,
    Sell,
}

impl Side {
    pub fn opposite(&self) -> Side {
        match self {
            Side::Buy => Side::Sell,
            Side::Sell => Side::Buy,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Side::Buy => "buy",
            Side::Sell => "sell",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OrderType {
    Limit,
    Market,
    Stop,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExitReason {
    StopHit,
    TargetHit,
    TimeStop,
    Invalidation,
    Deviation,
    Manual,
    TargetNearHit,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckResult {
    pub check_name: String,
    pub passed: bool,
    pub value: Decimal,
    pub limit: Decimal,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "request_type")]
pub enum GateRequest {
    GetPortfolio,
    GetOpenOrders,
    GetFillHistory {
        since: String,
    },
    GetMarketData {
        symbol: String,
    },

    SubmitOrder {
        strategy: String,
        symbol: String,
        side: Side,
        size: Decimal,
        order_type: OrderType,
        price: Option<Decimal>,
        stop_price: Option<Decimal>,
        thesis_slug: String,
        planned_entry: Decimal,
        planned_stop: Decimal,
    },

    CancelOrder {
        order_id: String,
    },

    TightenStop {
        order_id: String,
        new_stop: Decimal,
    },

    ProposeRule {
        proposal: RuleProposal,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "response_type", content = "payload")]
pub enum GateResponse {
    Accepted {
        order_id: String,
        checks_passed: Vec<CheckResult>,
    },
    Rejected {
        checks_failed: Vec<CheckResult>,
    },
    Portfolio(PortfolioState),
    Orders(Vec<Order>),
    Fills(Vec<Fill>),
    MarketData(MarketState),
    ProposalAcknowledged {
        proposal_id: String,
        auto_approved: bool,
        reason: String,
    },
    Error {
        message: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleProposal {
    pub proposal_type: RuleProposalType,
    pub rule_id: String,
    pub parameter: Option<String>,
    pub old_value: Option<Decimal>,
    pub new_value: Option<Decimal>,
    pub evidence: Option<String>,
    pub is_tightening: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuleProposalType {
    Activate,
    Suspend,
    ModifyParameter,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortfolioState {
    pub account_value: Decimal,
    pub available_cash: Decimal,
    pub total_exposure: Decimal,
    pub open_position_count: u32,
    pub daily_pnl: Decimal,
    pub weekly_pnl: Decimal,
    pub drawdown_from_peak: Decimal,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: String,
    pub strategy: String,
    pub symbol: String,
    pub side: Side,
    pub size: Decimal,
    pub order_type: OrderType,
    pub requested_price: Option<Decimal>,
    pub stop_price: Option<Decimal>,
    pub placed_at: DateTime<Utc>,
    pub status: OrderStatus,
    pub thesis_slug: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OrderStatus {
    Open,
    Filled,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fill {
    pub order_id: String,
    pub symbol: String,
    pub side: Side,
    pub size: Decimal,
    pub price: Decimal,
    pub fee: Decimal,
    pub filled_at: DateTime<Utc>,
    pub strategy: String,
    pub thesis_slug: String,
    pub is_entry: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MarketState {
    pub symbol: String,
    pub price: Decimal,
    pub spread_pct: Decimal,
    pub volume_ratio: Decimal,
    pub realized_volatility: Decimal,
    pub funding_rate_zscore: Decimal,
    pub regime_id: String,
    pub minute: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradeRecord {
    pub slug: String,
    pub strategy: String,
    pub symbol: String,
    pub side: Side,
    pub entry_time: DateTime<Utc>,
    pub entry_price: Decimal,
    pub entry_planned_price: Decimal,
    pub entry_size: Decimal,
    pub exit_time: Option<DateTime<Utc>>,
    pub exit_price: Option<Decimal>,
    pub pnl: Option<Decimal>,
    pub commissions: Option<Decimal>,
    pub mae: Option<Decimal>,
    pub mfe: Option<Decimal>,
    pub hold_minutes: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SafetyConfig {
    pub hard_limits: HardLimits,
    pub kill_switches: KillSwitches,
    pub dead_man_switch: Option<DeadManSwitch>,
    #[serde(default)]
    pub restricted_windows: Vec<RestrictedWindow>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardLimits {
    pub max_total_capital: Decimal,
    pub max_single_position_pct: Decimal,
    pub max_single_trade_risk_pct: Decimal,
    pub max_total_exposure_pct: Decimal,
    pub max_daily_loss: Decimal,
    pub max_weekly_loss: Decimal,
    pub max_drawdown_from_peak_pct: Decimal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KillSwitches {
    pub daily_loss_halt: bool,
    pub weekly_loss_halt: bool,
    pub drawdown_halt: bool,
    pub manual_halt: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeadManSwitch {
    pub enabled: bool,
    pub timeout_minutes: i64,
    pub action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestrictedWindow {
    pub day_of_week: Option<u32>,
    pub hour_start_utc: Option<u32>,
    pub hour_end_utc: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyConfig {
    pub name: String,
    pub status: String,
    pub capital_allocation: Decimal,
    pub instruments: Vec<String>,
    pub timeframe: String,
    pub parameters: serde_yaml::Value,
    pub parameter_bounds: serde_yaml::Value,
    pub version: Option<u32>,
    pub created: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ParsedDecimal(pub Decimal);

pub fn decimal_eq(a: Decimal, b: Decimal) -> bool {
    (a - b).abs() < 1e-9
}
