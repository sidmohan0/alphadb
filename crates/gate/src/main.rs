mod audit;
mod config;
mod db;
mod exchange;
mod rule_engine;
mod risk;
mod state;
mod validator;

use anyhow::{Context, Result};
use chrono::Utc;
use config::GateConfig;
use db::Db;
use exchange::{ExchangeConfig, ExchangeResult, ExchangeClient};
use rule_engine::RuleEngine;
use risk::validate_request;
use state::GateState;
use std::{env, path::Path, sync::Arc};
use tokio::{
    io::{split, AsyncBufReadExt, AsyncWriteExt, BufReader},
    net::{UnixListener, UnixStream},
    sync::Mutex,
};
use trading_common::{
    CheckResult, Fill, GateRequest, GateResponse, MarketState, Order, OrderStatus, Side,
};
use uuid::Uuid;

#[derive(Clone)]
struct RuntimeConfig {
    socket: String,
    config_path: String,
    active_rules: String,
    audit_path: String,
    db_path: String,
    product: String,
    exchange: String,
    api_key: Option<String>,
    api_secret: Option<String>,
    api_passphrase: Option<String>,
    api_base_url: String,
    dry_run: bool,
    initial_account_value: Option<f64>,
    initial_available_cash: Option<f64>,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    let rt_cfg = RuntimeConfig {
        socket: env::var("TRADING_GATE_SOCKET").unwrap_or_else(|_| "/tmp/trading-gate.sock".to_string()),
        config_path: env::var("TRADING_GATE_SAFETY_CONFIG").unwrap_or_else(|_| "config/safety.yaml".to_string()),
        active_rules: env::var("TRADING_GATE_RULES_DIR").unwrap_or_else(|_| "config/rules/active".to_string()),
        audit_path: env::var("TRADING_GATE_AUDIT_LOG").unwrap_or_else(|_| "data/audit.log".to_string()),
        db_path: env::var("TRADING_GATE_DB").unwrap_or_else(|_| "data/trades.db".to_string()),
        product: env::var("TRADING_GATE_PRODUCT")
            .or_else(|_| env::var("TRADING_AGENT_PRODUCT"))
            .unwrap_or_else(|_| "BTC-USD".to_string()),
        exchange: env::var("TRADING_GATE_EXCHANGE").unwrap_or_else(|_| "coinbase_advanced".to_string()),
        api_key: read_first_env(&[
            "COINBASE_API_KEY",
            "TRADING_GATE_API_KEY",
            "API_KEY",
        ]),
        api_secret: read_first_env(&[
            "COINBASE_API_SECRET",
            "TRADING_GATE_API_SECRET",
            "API_SECRET",
        ]),
        api_passphrase: read_first_env(&[
            "COINBASE_API_PASSPHRASE",
            "TRADING_GATE_API_PASSPHRASE",
            "API_PASSPHRASE",
        ]),
        api_base_url: env::var("TRADING_GATE_COINBASE_API_BASE_URL")
            .or_else(|_| env::var("COINBASE_API_BASE_URL"))
            .unwrap_or_else(|_| "https://api.exchange.coinbase.com".to_string()),
        dry_run: read_bool_env(&["TRADING_GATE_DRY_RUN", "COINBASE_DRY_RUN"], true),
        initial_account_value: env::var("TRADING_GATE_INITIAL_ACCOUNT_VALUE")
            .ok()
            .and_then(|value| value.parse::<f64>().ok()),
        initial_available_cash: env::var("TRADING_GATE_INITIAL_AVAILABLE_CASH")
            .ok()
            .and_then(|value| value.parse::<f64>().ok()),
    };

    let exchange_name = rt_cfg.exchange.to_lowercase();
    let effective_dry_run = if !has_required_credentials(
        &exchange_name,
        &rt_cfg.api_key,
        &rt_cfg.api_secret,
        &rt_cfg.api_passphrase,
    ) {
        if rt_cfg.dry_run {
            true
        } else {
            tracing::warn!("exchange credentials missing for {}, forcing dry_run mode", exchange_name);
            true
        }
    } else {
        rt_cfg.dry_run
    };

    tracing::info!(
        "trading-gate config product={} exchange={} dry_run={}",
        rt_cfg.product, exchange_name, effective_dry_run
    );
    tracing::info!(
        "exchange credentials configured key={} secret={} passphrase={}",
        rt_cfg.api_key.is_some(),
        rt_cfg.api_secret.is_some(),
        rt_cfg.api_passphrase.is_some()
    );

    let exchange = Arc::new(ExchangeClient::from_config(
        ExchangeConfig {
            exchange: exchange_name.clone(),
            api_key: rt_cfg.api_key,
            api_secret: rt_cfg.api_secret,
            api_passphrase: rt_cfg.api_passphrase,
            api_base_url: rt_cfg.api_base_url.clone(),
        },
        effective_dry_run,
    ));

    tracing::info!(
        exchange = exchange.exchange_name(),
        dry_run = exchange.is_dry_run(),
        base_url = rt_cfg.api_base_url,
        product = rt_cfg.product,
        "exchange runtime initialized"
    );

    let mut initial_state = GateState::default();
    if !exchange.is_dry_run() {
        match exchange.get_account_snapshot().await {
            Ok(account) => {
                initial_state.cash = account.available_cash;
                initial_state.account_value = account.account_value;
                initial_state.equity_peak = account.account_value.max(initial_state.equity_peak);
                tracing::info!(
                    exchange = exchange.exchange_name(),
                    available_cash = account.available_cash,
                    account_value = account.account_value,
                    currency = account.currency.unwrap_or_else(|| "USD".to_string()),
                    "connected_to_coinbase: seeded live account state"
                );
            }
            Err(err) => {
                if let Some(cash) = rt_cfg.initial_available_cash {
                    initial_state.cash = cash;
                }
                if let Some(account_value) = rt_cfg.initial_account_value {
                    initial_state.account_value = account_value;
                    initial_state.equity_peak = account_value.max(initial_state.equity_peak);
                }
                tracing::warn!(
                    exchange = exchange.exchange_name(),
                    product = rt_cfg.product,
                    error = %err,
                    account_value = initial_state.account_value,
                    available_cash = initial_state.cash,
                    "connected_to_coinbase: account snapshot failed; using configured fallback"
                );
            }
        }

        match exchange.get_market_price(&rt_cfg.product).await {
            Ok(price) => {
                tracing::info!(
                    product = rt_cfg.product,
                    live_price = price.price,
                    bid = price.bid,
                    ask = price.ask,
                    "connected_to_coinbase: reachable market endpoint"
                );
            }
            Err(err) => {
                tracing::warn!(
                    product = rt_cfg.product,
                    error = %err,
                    "connected_to_coinbase: market endpoint check failed"
                );
            }
        }
    } else {
        tracing::warn!(
            "Running in dry-run mode. Remove/disable TRADING_GATE_DRY_RUN to submit live orders.",
        );
    }

    tokio::fs::create_dir_all("data").await?;
    tokio::fs::create_dir_all("config/rules").await?;

    let config = GateConfig::load(&rt_cfg.config_path)?;
    let rule_engine = RuleEngine::load(&rt_cfg.active_rules)?;
    let audit = Arc::new(audit::AuditLog::new(&rt_cfg.audit_path));
    let db = Arc::new(Db::new(&rt_cfg.db_path)?);

    if Path::new(&rt_cfg.socket).exists() {
        let _ = std::fs::remove_file(&rt_cfg.socket);
    }

    let listener = UnixListener::bind(&rt_cfg.socket).context("bind unix socket")?;
    tracing::info!("trading-gate listening on {}", rt_cfg.socket);

    let state = Arc::new(Mutex::new(initial_state));
    let market_cache = Arc::new(Mutex::new(seed_market(&rt_cfg.product)));
    let rule_engine = Arc::new(rule_engine);

    loop {
        let (stream, _) = listener.accept().await.context("accept client")?;
        handle_client(
            stream,
            state.clone(),
            config.safety.clone(),
            db.clone(),
            audit.clone(),
            market_cache.clone(),
            rule_engine.clone(),
            exchange.clone(),
        )
        .await?;
    }
}

fn has_required_credentials(
    exchange: &str,
    api_key: &Option<String>,
    api_secret: &Option<String>,
    api_passphrase: &Option<String>,
) -> bool {
    if exchange.contains("advanced") {
        api_key.is_some() && api_secret.is_some()
    } else {
        api_key.is_some() && api_secret.is_some() && api_passphrase.is_some()
    }
}

fn seed_market(symbol: &str) -> MarketState {
    MarketState {
        symbol: symbol.to_string(),
        price: 10000.0,
        spread_pct: 0.001,
        volume_ratio: 1.0,
        realized_volatility: 0.35,
        funding_rate_zscore: 0.0,
        regime_id: "ranging".to_string(),
        minute: Utc::now(),
    }
}

async fn handle_client(
    stream: UnixStream,
    state: Arc<Mutex<GateState>>,
    safety: trading_common::SafetyConfig,
    db: Arc<Db>,
    audit: Arc<audit::AuditLog>,
    market_cache: Arc<Mutex<MarketState>>,
    rule_engine: Arc<RuleEngine>,
    exchange: Arc<ExchangeClient>,
) -> Result<()> {
    let validator = validator::GateValidator::new((*rule_engine).clone());

    let (read_half, mut writer) = split(stream);
    let mut reader = BufReader::new(read_half);
    let mut line = String::new();

    loop {
        line.clear();
        let n = reader.read_line(&mut line).await?;
        if n == 0 {
            break;
        }

        let req = match serde_json::from_str::<GateRequest>(line.trim()) {
            Ok(r) => r,
            Err(err) => {
                send_json(
                    &mut writer,
                    &GateResponse::Error {
                        message: format!("invalid request payload: {err}"),
                    },
                )
                .await?;
                continue;
            }
        };

        if matches!(req, GateRequest::GetMarketData { .. }) {
            let mut m = market_cache.lock().await;
            *m = refresh_market(&m);
        }

        let response =
            process_request(req, &state, &safety, &db, &audit, &market_cache, &validator, &exchange).await;
        send_json(&mut writer, &response).await?;
    }

    Ok(())
}

async fn process_request(
    req: GateRequest,
    state: &Arc<Mutex<GateState>>,
    safety: &trading_common::SafetyConfig,
    db: &Arc<Db>,
    audit: &audit::AuditLog,
    market_cache: &Arc<Mutex<MarketState>>,
    validator: &validator::GateValidator,
    exchange: &ExchangeClient,
) -> GateResponse {
    use GateRequest::*;

    match req {
        GetPortfolio => {
            let guard = state.lock().await;
            GateResponse::Portfolio(guard.portfolio_state())
        }
        GetOpenOrders => {
            let guard = state.lock().await;
            GateResponse::Orders(guard.orders.values().cloned().collect())
        }
        GetFillHistory { since } => match chrono::DateTime::parse_from_rfc3339(&since) {
            Ok(ts) => {
                let since = ts.with_timezone(&Utc);
                match db.fills_since(since) {
                    Ok(fills) => GateResponse::Fills(fills),
                    Err(err) => GateResponse::Error {
                        message: format!("db read fills failed: {err}"),
                    },
                }
            }
            Err(err) => GateResponse::Error {
                message: format!("invalid since timestamp: {err}"),
            },
        },
        GetMarketData { symbol } => {
            let mut m = market_cache.lock().await;
            if !exchange.is_dry_run() {
                if let Ok(tick) = exchange.get_market_price(&symbol).await {
                    let spread_pct = if let (Some(bid), Some(ask)) = (tick.bid, tick.ask) {
                        if tick.price > 0.0 {
                            ((ask - bid).abs() / tick.price).abs()
                        } else {
                            0.001
                        }
                    } else {
                        0.001
                    };

                    m.price = tick.price;
                    m.spread_pct = spread_pct;
                    m.realized_volatility = tick.mark.unwrap_or(m.realized_volatility);
                    m.regime_id = if spread_pct > 0.0025 {
                        "volatile_spread".to_string()
                    } else {
                        "ranging".to_string()
                    };
                    m.minute = Utc::now();
                } else {
                    *m = refresh_market(&m);
                }
            } else {
                *m = refresh_market(&m);
            }
            m.symbol = symbol;
            GateResponse::MarketData(m.clone())
        }
        CancelOrder { order_id } => {
            let mut guard = state.lock().await;
            if guard.orders.remove(&order_id).is_some() {
                GateResponse::Accepted {
                    order_id,
                    checks_passed: vec![CheckResult {
                        check_name: "cancel".to_string(),
                        passed: true,
                        value: 1.0,
                        limit: 1.0,
                        source: "agent_api".to_string(),
                    }],
                }
            } else {
                GateResponse::Rejected {
                    checks_failed: vec![CheckResult {
                        check_name: "order_not_found".to_string(),
                        passed: false,
                        value: 0.0,
                        limit: 1.0,
                        source: "agent_api".to_string(),
                    }],
                }
            }
        }
        TightenStop { .. } => GateResponse::Accepted {
            order_id: "stop_tighten_ack".to_string(),
            checks_passed: vec![CheckResult {
                check_name: "tighten_stop".to_string(),
                passed: true,
                value: 1.0,
                limit: 1.0,
                source: "agent_api".to_string(),
            }],
        },
        ProposeRule { proposal } => {
            let is_tightening = proposal.is_tightening.unwrap_or(false);
            let (dir, reason) = if is_tightening {
                ("proposals/applied", "tightening rules auto-approved")
            } else {
                ("proposals/pending", "requires_human review")
            };

            let _ = tokio::fs::create_dir_all(dir).await;
            let path = format!("{dir}/{}.json", proposal.rule_id);
            if let Ok(body) = serde_json::to_string(&proposal) {
                let _ = tokio::fs::write(path, body).await;
            }
            let _ = audit.log_proposal(&proposal.rule_id, is_tightening, reason);

            GateResponse::ProposalAcknowledged {
                proposal_id: proposal.rule_id,
                auto_approved: is_tightening,
                reason: reason.to_string(),
            }
        }
        SubmitOrder {
            strategy,
            symbol,
            side,
            size,
            order_type,
            price: _price,
            stop_price,
            thesis_slug,
            planned_entry,
            planned_stop,
        } => {
            let request = GateRequest::SubmitOrder {
                strategy: strategy.clone(),
                symbol: symbol.clone(),
                side,
                size,
                order_type,
                price: Some(planned_entry),
                stop_price,
                thesis_slug: thesis_slug.clone(),
                planned_entry,
                planned_stop,
            };

            let market = market_cache.lock().await.clone();
            let mut guard = state.lock().await;
            let checks = validate_request(&request, safety, &guard.portfolio_state(), market.price);
            let risk_ctx = match validator.evaluate(&request, &guard, checks, &market) {
                Ok(ctx) => ctx,
                Err(err) => {
                    return GateResponse::Error {
                        message: format!("validation failure: {err}"),
                    };
                }
            };

            let _ = audit.log_submit_decision(&request, &risk_ctx.checks, risk_ctx.can_trade, None);
            if !risk_ctx.can_trade {
                return GateResponse::Rejected {
                    checks_failed: risk_ctx.checks.into_iter().filter(|c| !c.passed).collect(),
                };
            }

            let mut checks = risk_ctx.checks;
            checks.push(CheckResult {
                check_name: "stop_order_verified".to_string(),
                passed: stop_price.is_some(),
                value: if stop_price.is_some() { 1.0 } else { 0.0 },
                limit: 1.0,
                source: "gate".to_string(),
            });

            let now = Utc::now();
            let order_id = Uuid::new_v4().to_string();
            let desired_entry = if planned_entry > 0.0 { planned_entry } else { market.price };

            let execution: ExchangeResult = match exchange
                .submit_order(&order_id, &symbol, side, size, order_type, desired_entry)
                .await
            {
                Ok(exec) => {
                    tracing::info!(
                        exchange_order_id = exec.exchange_order_id.as_deref().unwrap_or("n/a"),
                        executed_size = exec.executed_size,
                        fill_price = exec.executed_price,
                        "order submitted to exchange"
                    );
                    exec
                }
                Err(err) => {
                    return GateResponse::Error {
                        message: format!("exchange submit failed: {err}"),
                    };
                }
            };

            let fill_price = execution.executed_price.max(1.0);
            let fee = execution.fee;

            if let Some((pos_id, pos)) = find_matching_exit_position(&mut guard, &strategy, &symbol, side) {
                let close_size = size.min(pos.size);
                let realized =
                    (fill_price - pos.entry_price) * close_size * if side == Side::Buy { 1.0 } else { -1.0 };

                guard.cash += realized - fee;
                guard.account_value += realized;

                let exit_fill = Fill {
                    order_id: order_id.clone(),
                    symbol: pos.symbol.clone(),
                    side,
                    size: close_size,
                    price: fill_price,
                    fee,
                    filled_at: now,
                    strategy: pos.strategy.clone(),
                    thesis_slug: pos.thesis_slug.clone(),
                    is_entry: false,
                };
                let _ = db.insert_fill(&exit_fill);
                guard.fills.push(exit_fill.clone());
                guard.add_fill(exit_fill.clone());

                if close_size >= pos.size - 1e-12 {
                    guard.positions.remove(&pos_id);
                    let _ = db.remove_position(&pos_id);
                }

                GateResponse::Accepted {
                    order_id,
                    checks_passed: checks,
                }
            } else {
                let order = Order {
                    id: order_id.clone(),
                    strategy: strategy.clone(),
                    symbol: symbol.clone(),
                    side,
                    size,
                    order_type,
                    requested_price: Some(fill_price),
                    stop_price,
                    placed_at: now,
                    status: OrderStatus::Filled,
                    thesis_slug: thesis_slug.clone(),
                };
                guard.orders.insert(order.id.clone(), order.clone());

                let position = state::Position {
                    id: order_id.clone(),
                    strategy: strategy.clone(),
                    symbol: symbol.clone(),
                    side,
                    size,
                    entry_price: fill_price,
                    entry_time: now,
                    thesis_slug: thesis_slug.clone(),
                    stop_price,
                };
                guard.positions.insert(order_id.clone(), position);
                let _ = db.upsert_position(&order, fill_price, now);

                let entry_fill = Fill {
                    order_id: order_id.clone(),
                    symbol,
                    side,
                    size,
                    price: fill_price,
                    fee,
                    filled_at: now,
                    strategy,
                    thesis_slug,
                    is_entry: true,
                };
                let _ = db.insert_fill(&entry_fill);
                guard.fills.push(entry_fill.clone());
                guard.add_fill(entry_fill);

                GateResponse::Accepted {
                    order_id,
                    checks_passed: checks,
                }
            }
        }
    }
}

fn find_matching_exit_position(
    state: &mut GateState,
    strategy: &str,
    symbol: &str,
    entry_side: Side,
) -> Option<(String, state::Position)> {
    let exit_side = entry_side.opposite();
    let id = state
        .positions
        .iter()
        .find(|(_, p)| p.strategy == strategy && p.symbol == symbol && p.side == exit_side)
        .map(|(id, _)| id.clone())?;

    state.positions.remove_entry(&id)
}

fn refresh_market(current: &MarketState) -> MarketState {
    let seconds = (Utc::now().timestamp() % 120) as f64;
    let drift = (seconds - 60.0) * 0.0001;
    let next_price = (current.price * (1.0 + drift)).max(1.0);
    let funding = ((Utc::now().timestamp() % 20) as f64 / 10.0) - 1.0;

    MarketState {
        symbol: current.symbol.clone(),
        price: next_price,
        spread_pct: 0.001,
        volume_ratio: 1.0,
        realized_volatility: 0.35,
        funding_rate_zscore: funding,
        regime_id: if funding.abs() < 0.5 {
            "ranging".to_string()
        } else if funding > 0.0 {
            "volatile_crisis".to_string()
        } else {
            "volatile_mean_reverting".to_string()
        },
        minute: Utc::now(),
    }
}

fn read_first_env(names: &[&str]) -> Option<String> {
    for name in names {
        if let Ok(value) = env::var(name) {
            if !value.trim().is_empty() {
                return Some(value);
            }
        }
    }
    None
}

fn read_bool_env(names: &[&str], default: bool) -> bool {
    for name in names {
        if let Ok(value) = env::var(name) {
            let value = value.trim().to_lowercase();
            if value == "1" || value == "true" || value == "yes" || value == "on" {
                return true;
            }
            if value == "0" || value == "false" || value == "no" || value == "off" {
                return false;
            }
        }
    }
    default
}

async fn send_json<W>(writer: &mut W, msg: &GateResponse) -> Result<()>
where
    W: tokio::io::AsyncWrite + Unpin,
{
    let payload = serde_json::to_string(msg)?;
    writer.write_all(payload.as_bytes()).await?;
    writer.write_all(b"\n").await?;
    writer.flush().await?;
    Ok(())
}
