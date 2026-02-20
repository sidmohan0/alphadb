mod config;
mod feedback;
mod ipc_client;
mod strategy;

use anyhow::{Context, Result};
use chrono::{DateTime, Duration, Timelike, Utc};
use feedback::loop1::Loop1;
use ipc_client::GateClient;
use std::{collections::HashMap, fs, path::Path, time::Duration as StdDuration};
use strategy::{Signal, StrategyContext, StrategyPolicy};
use tokio::{runtime::Builder, time};
use trading_common::{GateRequest, GateResponse, Side};

#[derive(Clone)]
struct ActiveTrade {
    slug: String,
    strategy: String,
    symbol: String,
    side: Side,
    size: f64,
    _plan_entry: f64,
    plan_stop: f64,
    opened_at: DateTime<Utc>,
}

fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    let cfg = config::load_config();
    let strategy_config = config::load_strategy_config(&cfg.strategy_path)
        .with_context(|| "loading strategy config")?;

    let product = config::current_product(
        strategy_config
            .instruments
            .first()
            .cloned()
            .as_deref()
            .unwrap_or("BTC-USD"),
    );

    tokio_main(cfg, strategy_config, product)
}

fn tokio_main(cfg: config::AgentConfig, strategy_cfg: trading_common::StrategyConfig, product: String) -> Result<()> {
    let rt = Builder::new_multi_thread().enable_all().build()?;
    rt.block_on(async move {
        bootstrap_workspace()?;

        let strategy = StrategyPolicy::from_config(strategy_cfg, 10_000.0);
        let client = GateClient::new(cfg.socket.clone());

        let mut loop1 = Loop1::default();
        let mut active: HashMap<String, ActiveTrade> = HashMap::new();
        let mut last_fill_cursor = Utc::now() - Duration::hours(1);

        loop {
            let market = match client
                .send(&GateRequest::GetMarketData { symbol: product.clone() })
                .await
            {
                Ok(GateResponse::MarketData(state)) => state,
                _ => {
                    tracing::warn!("market request failed, retrying");
                    time::sleep(StdDuration::from_secs(cfg.cycle_secs)).await;
                    continue;
                }
            };

            if let Ok(portfolio) = client.send(&GateRequest::GetPortfolio).await {
                if let GateResponse::Portfolio(p) = portfolio {
                    tracing::info!("portfolio account={} cash={}", p.account_value, p.available_cash);
                }
            }

            if let Ok(GateResponse::Fills(fills)) = client
                .send(&GateRequest::GetFillHistory {
                    since: last_fill_cursor.to_rfc3339(),
                })
                .await
            {
                loop1.on_fills(&fills)?;
                if let Some(last) = fills.first() {
                    last_fill_cursor = last.filled_at;
                }
            }

            if active.is_empty() {
                let ctx = StrategyContext {
                    symbol: product.clone(),
                    price: market.price,
                    funding_zscore: market.funding_rate_zscore,
                    hour: Utc::now().hour(),
                    _product: product.clone(),
                };

                if let Some(signal) = strategy.generate(&ctx) {
                    let planned_entry = signal.planned_entry;
                    let planned_stop = signal.planned_stop;
                    let strategy_name = strategy.name.clone();
                    let symbol = signal.symbol.clone();
                    let side = signal.side;
                    let size = strategy.size_for(signal.planned_entry).max(0.0);
                    let request = GateRequest::SubmitOrder {
                        strategy: strategy_name.clone(),
                        symbol: symbol.clone(),
                        side,
                        size,
                        order_type: trading_common::OrderType::Limit,
                        price: Some(planned_entry),
                        stop_price: Some(planned_stop),
                        thesis_slug: signal.thesis_slug.clone(),
                        planned_entry,
                        planned_stop,
                    };

                    match client.send(&request).await? {
                        GateResponse::Accepted { order_id, checks_passed } => {
                            tracing::info!("entry accepted order={order_id} checks={checks_passed:?}");
                            write_plan(&signal, &strategy_name, &symbol, side, planned_entry, planned_stop, order_id.clone())?;
                            active.insert(
                                order_id,
                                ActiveTrade {
                                    slug: signal.thesis_slug,
                                    strategy: strategy_name,
                                    symbol,
                                    side,
                                    size,
                                    _plan_entry: planned_entry,
                                    plan_stop: planned_stop,
                                    opened_at: Utc::now(),
                                },
                            );
                        }
                        GateResponse::Rejected { checks_failed } => {
                            tracing::warn!("entry rejected checks={checks_failed:?}");
                            write_counterfactual_if_blocked(&signal, &checks_failed)?;
                        }
                        _ => {}
                    }
                }
            }

            let now = Utc::now();
            for (order_id, trade) in active.clone().into_iter() {
                if now.signed_duration_since(trade.opened_at) > Duration::minutes(10) {
                    let exit_side = trade.side.opposite();
                    let exit_req = GateRequest::SubmitOrder {
                        strategy: trade.strategy,
                        symbol: trade.symbol,
                        side: exit_side,
                        size: trade.size,
                        order_type: trading_common::OrderType::Market,
                        price: Some(market.price),
                        stop_price: Some(trade.plan_stop),
                        thesis_slug: trade.slug,
                        planned_entry: market.price,
                        planned_stop: trade.plan_stop,
                    };
                    let _ = client.send(&exit_req).await;
                    active.remove(&order_id);
                }
            }

            time::sleep(StdDuration::from_secs(cfg.cycle_secs)).await;
        }
    })
}

fn bootstrap_workspace() -> Result<()> {
    for d in [
        "journal",
        "journal/theses",
        "journal/plans",
        "journal/plans/active",
        "journal/plans/completed",
        "journal/research",
        "journal/spikes",
        "docs",
        "docs/strategies",
        "docs/runbooks",
        "docs/retired-rules",
        "data",
        "proposals",
        "proposals/pending",
        "proposals/applied",
        "proposals/rejected",
        "config/rules/active",
        "config/rules/core",
        "config/rules",
        "data/portfolio/snapshots",
        "data/performance",
    ] {
        fs::create_dir_all(d)?;
    }
    Ok(())
}

fn write_plan(
    signal: &Signal,
    strategy_name: &str,
    symbol: &str,
    side: Side,
    planned_entry: f64,
    planned_stop: f64,
    order_id: String,
) -> Result<()> {
    let now = Utc::now().format("%Y-%m-%d-%H%M%S").to_string();
    let path = Path::new("journal/plans/active").join(format!("{now}-{symbol}.md"));

    let mut side_text = "buy";
    if matches!(side, Side::Sell) {
        side_text = "sell";
    }

    let mut plan = String::new();
    plan.push_str(&format!(
        "---\nslug: {now}\ndate: {}\nstatus: active\nstrategy: {}\nside: {}\nconviction: medium\nplan_mode: scalp\n---\n\n",
        Utc::now().to_rfc3339(),
        strategy_name,
        side_text
    ));
    plan.push_str("## Thesis Summary\n");
    plan.push_str(&format!(
        "Signal based on funding z-score {:.2} (strength {:.2}).\n\n",
        signal.funding_zscore, signal.strength
    ));
    plan.push_str("## Instrument Selection\n");
    plan.push_str(&format!("- symbol: {}\n\n", symbol));
    plan.push_str("## Entry Criteria\n");
    plan.push_str(&format!("- planned_entry: {}\n", planned_entry));
    plan.push_str("## Stop Loss\n");
    plan.push_str(&format!("- stop: {}\n", planned_stop));
    plan.push_str("## Progress\n");
    plan.push_str(&format!("- order_id: {}\n", order_id));

    fs::write(path, plan).context("write plan artifact")
}

fn write_counterfactual_if_blocked(signal: &Signal, checks: &[trading_common::CheckResult]) -> Result<()> {
    let file = format!(
        "journal/plans/active/blocked-{}-{}.md",
        signal.symbol,
        chrono::Utc::now().format("%Y%m%d-%H%M%S")
    );
    let mut body = format!(
        "# Blocked entry\n\nSignal {} would have entered {}\n\nChecks:\n",
        signal.thesis_slug, signal.side.as_str()
    );
    for c in checks {
        body.push_str(&format!(
            "- {} => passed={} value={} limit={}\n",
            c.check_name, c.passed, c.value, c.limit
        ));
    }
    fs::write(file, body)?;
    Ok(())
}
