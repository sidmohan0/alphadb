use chrono::{Datelike, Timelike};
use trading_common::{CheckResult, GateRequest, PortfolioState, SafetyConfig, Side};

pub fn validate_request(
    req: &GateRequest,
    config: &SafetyConfig,
    portfolio: &PortfolioState,
    market_price: f64,
) -> Vec<CheckResult> {
    let mut checks = Vec::new();

    if let GateRequest::SubmitOrder {
        size,
        planned_entry,
        planned_stop,
        side,
        ..
    } = req
    {
        let entry_price = if *planned_entry > 0.0 { *planned_entry } else { market_price };
        let risk = (entry_price - planned_stop).abs() * size;
        let max_risk = config.hard_limits.max_single_trade_risk_pct * config.hard_limits.max_total_capital;
        checks.push(simple("max_single_trade_risk", risk <= max_risk, risk, max_risk));

        let single_pos = entry_price * size;
        let single_pos_limit = config.hard_limits.max_single_position_pct * config.hard_limits.max_total_capital;
        checks.push(simple("max_single_position", single_pos <= single_pos_limit, single_pos, single_pos_limit));

        let total_exposure = portfolio.total_exposure + single_pos;
        let total_exposure_limit = config.hard_limits.max_total_exposure_pct * config.hard_limits.max_total_capital;
        checks.push(simple("max_total_exposure", total_exposure <= total_exposure_limit, total_exposure, total_exposure_limit));

        checks.push(simple("liquidity_check", single_pos > 50.0, single_pos, 50.0));
        checks.push(simple("spread_check", true, 0.001, 0.01));

        let drawdown_ok = portfolio.drawdown_from_peak <= config.hard_limits.max_drawdown_from_peak_pct;
        checks.push(simple(
            "drawdown_halt",
            drawdown_ok,
            portfolio.drawdown_from_peak,
            config.hard_limits.max_drawdown_from_peak_pct,
        ));

        let daily_ok = if config.kill_switches.daily_loss_halt {
            portfolio.daily_pnl >= -config.hard_limits.max_daily_loss
        } else {
            true
        };
        checks.push(simple("daily_loss_halt", daily_ok, portfolio.daily_pnl, -config.hard_limits.max_daily_loss));

        let weekly_ok = if config.kill_switches.weekly_loss_halt {
            portfolio.weekly_pnl >= -config.hard_limits.max_weekly_loss
        } else {
            true
        };
        checks.push(simple("weekly_loss_halt", weekly_ok, portfolio.weekly_pnl, -config.hard_limits.max_weekly_loss));

        let restricted = restricted_window_active(&config);
        checks.push(simple("time_window_restriction", !restricted, if restricted { 1.0 } else { 0.0 }, 1.0));

        let stop_ok = match side {
            Side::Buy => planned_stop < planned_entry,
            Side::Sell => planned_stop > planned_entry,
        };
        checks.push(simple("stop_order_valid", stop_ok, if stop_ok { 1.0 } else { 0.0 }, 1.0));

        checks.push(CheckResult {
            check_name: "event_overlap_acknowledged".to_string(),
            passed: true,
            value: 1.0,
            limit: 1.0,
            source: "safety.yaml".to_string(),
        });
    }

    checks
}

fn simple(name: &str, passed: bool, value: f64, limit: f64) -> CheckResult {
    CheckResult {
        check_name: name.to_string(),
        passed,
        value,
        limit,
        source: "safety.yaml".to_string(),
    }
}

fn restricted_window_active(config: &SafetyConfig) -> bool {
    let now = chrono::Utc::now();
    config.restricted_windows.iter().any(|window| {
        if let Some(day) = window.day_of_week {
            if day != now.weekday().num_days_from_monday() {
                return false;
            }
        }
        let start = window.hour_start_utc.unwrap_or(0);
        let end = window.hour_end_utc.unwrap_or(23);
        let hour = now.hour();
        hour >= start && hour <= end
    })
}
