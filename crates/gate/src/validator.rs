use crate::{rule_engine::{EvaluatedRule, RuleAction, RuleEngine}, state::GateState};
use anyhow::Result;
use trading_common::{CheckResult, GateRequest, MarketState};

pub struct RiskContext {
    pub can_trade: bool,
    pub checks: Vec<CheckResult>,
}

pub struct GateValidator {
    pub rule_engine: RuleEngine,
}

impl GateValidator {
    pub fn new(rule_engine: RuleEngine) -> Self {
        Self { rule_engine }
    }

    pub fn evaluate(
        &self,
        req: &GateRequest,
        state: &GateState,
        mut checks: Vec<CheckResult>,
        market: &MarketState,
    ) -> Result<RiskContext> {
        let mut can_trade = true;

        if !state.can_trade || state.manual_halt {
            can_trade = false;
        }

        let rule_hits = self.rule_engine.evaluate(req, market, state.positions.len());
        for hit in rule_hits {
            apply_rule_hit(&hit, &mut checks, &mut can_trade);
        }

        if checks.iter().any(|c| !c.passed) {
            can_trade = false;
        }

        Ok(RiskContext {
            can_trade,
            checks,
        })
    }
}

fn apply_rule_hit(hit: &EvaluatedRule, checks: &mut Vec<CheckResult>, can_trade: &mut bool) {
    match hit.action {
        RuleAction::Reject => {
            *can_trade = false;
            checks.push(CheckResult {
                check_name: format!("rule:{}", hit.id),
                passed: false,
                value: 1.0,
                limit: 0.0,
                source: "rule-dsl".to_string(),
            });
        }
        RuleAction::Warn | RuleAction::ReduceSize => {
            checks.push(CheckResult {
                check_name: format!("rule:{}", hit.id),
                passed: true,
                value: 1.0,
                limit: 1.0,
                source: "rule-dsl".to_string(),
            });
        }
    }
}
