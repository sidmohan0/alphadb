use anyhow::{Context, Result};
use chrono::{Datelike, Timelike, Utc};
use serde::{Deserialize, Serialize};
use std::path::Path;

use trading_common::{GateRequest, MarketState};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum Operator {
    Eq,
    Neq,
    Gt,
    Gte,
    Lt,
    Lte,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Condition {
    field: String,
    operator: Operator,
    value: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum RuleAction {
    #[serde(rename = "reject")]
    Reject,
    #[serde(rename = "warn")]
    Warn,
    #[serde(rename = "reduce_size")]
    ReduceSize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleFile {
    pub id: String,
    #[serde(default)]
    pub status: String,
    pub strategy: Option<String>,
    #[serde(default)]
    pub conditions: Vec<Condition>,
    #[serde(default)]
    pub action: Option<RuleAction>,
    #[serde(default)]
    pub message: Option<String>,
}

#[derive(Debug, Clone)]
pub struct EvaluatedRule {
    pub id: String,
    pub action: RuleAction,
}

#[derive(Clone)]
pub struct RuleEngine {
    rules: Vec<RuleFile>,
}

impl RuleEngine {
    pub fn load(active_rules_dir: impl AsRef<Path>) -> Result<Self> {
        let mut rules = Vec::new();
        let dir = active_rules_dir.as_ref();
        if !dir.exists() {
            return Ok(Self { rules });
        }

        for entry in std::fs::read_dir(dir).context("read active rules dir")? {
            let path = entry?.path();
            if path.extension().and_then(|s| s.to_str()) != Some("yaml") {
                continue;
            }
            let content = std::fs::read_to_string(&path)
                .with_context(|| format!("reading rule file {:?}", path))?;
            if let Ok(rule) = serde_yaml::from_str::<RuleFile>(&content) {
                rules.push(rule);
            }
        }

        Ok(Self { rules })
    }

    pub fn evaluate(&self, req: &GateRequest, market: &MarketState, position_count: usize) -> Vec<EvaluatedRule> {
        self
            .rules
            .iter()
            .filter_map(|rule| {
                if let GateRequest::SubmitOrder { strategy, .. } = req {
                    if let Some(strategy_filter) = &rule.strategy {
                        if strategy_filter != strategy {
                            return None;
                        }
                    }
                }

                let all_match = rule.conditions.iter().all(|c| {
                    resolve_field(c.field.as_str(), req, market, position_count)
                        .map(|lhs| compare(lhs, &c.operator, &c.value))
                        .unwrap_or(false)
                });

                if all_match {
                    Some(EvaluatedRule {
                        id: rule.id.clone(),
                        action: rule.action.clone().unwrap_or(RuleAction::Warn),
                    })
                } else {
                    None
                }
            })
            .collect()
    }
}

fn compare(lhs: f64, op: &Operator, rhs_val: &serde_json::Value) -> bool {
    let rhs = rhs_val.as_f64().unwrap_or(0.0);
    match op {
        Operator::Eq => (lhs - rhs).abs() < 1e-9,
        Operator::Neq => (lhs - rhs).abs() >= 1e-9,
        Operator::Gt => lhs > rhs,
        Operator::Gte => lhs >= rhs,
        Operator::Lt => lhs < rhs,
        Operator::Lte => lhs <= rhs,
    }
}

fn resolve_field(field: &str, req: &GateRequest, market: &MarketState, open_positions: usize) -> Option<f64> {
    match field {
        "market.price" => Some(market.price),
        "market.funding_rate_zscore" => Some(market.funding_rate_zscore),
        "market.volume_ratio" => Some(market.volume_ratio),
        "market.volatility" => Some(market.realized_volatility),
        "market.spread_pct" => Some(market.spread_pct),
        "time.day_of_week" => Some(Utc::now().weekday().number_from_monday() as f64 - 1.0),
        "time.hour_utc" => Some(Utc::now().hour() as f64),
        "portfolio.total_exposure_pct" => Some(open_positions as f64 * 0.01),
        "portfolio.open_position_count" => Some(open_positions as f64),
        "order.size" => request_field_f64(req, |v| v.size),
        "order.notional" => match req {
            GateRequest::SubmitOrder {
                size,
                planned_entry,
                ..
            } => Some(size * planned_entry),
            _ => None,
        },
        "order.side" => match req {
            GateRequest::SubmitOrder { side, .. } => match side {
                trading_common::Side::Buy => Some(1.0),
                trading_common::Side::Sell => Some(-1.0),
            },
            _ => None,
        },
        "order.risk_pct" => match req {
            GateRequest::SubmitOrder {
                size,
                planned_entry,
                planned_stop,
                ..
            } => Some((planned_entry - planned_stop).abs() * size),
            _ => None,
        },
        _ => None,
    }
}

struct SubmitOrderLike {
    size: f64,
}

fn request_field_f64<F: Fn(&SubmitOrderLike) -> f64>(req: &GateRequest, f: F) -> Option<f64> {
    let obj = match req {
        GateRequest::SubmitOrder { size, .. } => Some(SubmitOrderLike { size: *size }),
        _ => None,
    }?;
    Some(f(&obj))
}
