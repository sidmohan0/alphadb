use anyhow::{anyhow, Context, Result};
use base64::Engine;
use hmac::{Hmac, Mac};
use jsonwebtoken::{encode, Algorithm, EncodingKey, Header};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};
use trading_common::{OrderType, Side};

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone)]
pub struct ExchangeConfig {
    pub exchange: String,
    pub api_key: Option<String>,
    pub api_secret: Option<String>,
    pub api_passphrase: Option<String>,
    pub api_base_url: String,
}

#[derive(Debug, Clone)]
pub struct ExchangeResult {
    pub exchange_order_id: Option<String>,
    pub executed_price: f64,
    pub executed_size: f64,
    pub fee: f64,
    pub filled: bool,
    pub raw: Value,
}

#[derive(Debug, Clone)]
pub struct CoinPrice {
    pub price: f64,
    pub bid: Option<f64>,
    pub ask: Option<f64>,
    pub mark: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct CoinBaseAccountSnapshot {
    pub available_cash: f64,
    pub account_value: f64,
    pub currency: Option<String>,
}

#[derive(Clone)]
pub struct ExchangeClient {
    dry_run: bool,
    exchange: String,
    mode: ExchangeAuthMode,
    http: Option<Client>,
    credentials: Option<ExchangeCredentials>,
    api_base_url: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExchangeAuthMode {
    Legacy,
    Advanced,
}

#[derive(Clone)]
struct ExchangeCredentials {
    api_key: String,
    api_secret: String,
    api_passphrase: Option<String>,
}

#[derive(Deserialize)]
struct CoinbaseOrderResponse {
    #[serde(default)]
    success: Option<bool>,
    #[serde(default)]
    success_response: Option<Value>,
    #[serde(default)]
    error: Option<Value>,
    #[serde(default)]
    error_response: Option<Value>,
    #[serde(default)]
    errors: Option<Value>,
}

#[derive(Serialize)]
struct CoinbaseJwtClaims {
    iss: &'static str,
    sub: String,
    aud: &'static str,
    uri: String,
    nbf: i64,
    exp: i64,
}

impl ExchangeClient {
    pub fn from_config(cfg: ExchangeConfig, dry_run: bool) -> Self {
        let exchange = cfg.exchange.to_lowercase();
        let mode = exchange_auth_mode(&exchange);

        let has_credentials = match mode {
            ExchangeAuthMode::Advanced => cfg.api_key.is_some() && cfg.api_secret.is_some(),
            ExchangeAuthMode::Legacy => {
                cfg.api_key.is_some() && cfg.api_secret.is_some() && cfg.api_passphrase.is_some()
            }
        };

        let credentials = if has_credentials {
            Some(ExchangeCredentials {
                api_key: cfg.api_key.unwrap_or_default(),
                api_secret: cfg.api_secret.unwrap_or_default(),
                api_passphrase: cfg.api_passphrase,
            })
        } else {
            None
        };

        let http = if dry_run { None } else { Some(Client::new()) };

        Self {
            dry_run: dry_run || credentials.is_none(),
            exchange,
            mode,
            http,
            credentials,
            api_base_url: cfg.api_base_url,
        }
    }

    pub fn is_dry_run(&self) -> bool {
        self.dry_run
    }

    pub fn exchange_name(&self) -> &str {
        &self.exchange
    }

    pub async fn get_market_price(&self, symbol: &str) -> Result<CoinPrice> {
        if self.dry_run {
            return Err(anyhow!("exchange disabled in dry-run mode"));
        }

        match self.mode {
            ExchangeAuthMode::Legacy | ExchangeAuthMode::Advanced => self.coinbase_get_price(symbol).await,
        }
    }

    pub async fn get_account_snapshot(&self) -> Result<CoinBaseAccountSnapshot> {
        if self.dry_run {
            return Err(anyhow!("exchange disabled in dry-run mode"));
        }

        let creds = self
            .credentials
            .as_ref()
            .context("exchange credentials are required for live mode")?;

        let request_path = "/api/v3/brokerage/accounts";
        let raw = match self.mode {
            ExchangeAuthMode::Legacy => {
                let timestamp = now_secs();
                let signature = sign_coinbase_hmac(
                    &timestamp,
                    "GET",
                    request_path,
                    "",
                    &creds.api_secret,
                )?;
                self.send_json(
                    "GET",
                    request_path,
                    Some((
                        creds.api_key.clone(),
                        Some(signature),
                        Some(timestamp),
                        creds.api_passphrase.clone().unwrap_or_default(),
                        None,
                    )),
                    None,
                )
                .await?
            }
            ExchangeAuthMode::Advanced => {
                let token = sign_coinbase_advanced_jwt(
                    &creds.api_key,
                    &creds.api_secret,
                    "GET",
                    request_path,
                    "",
                )?;
                self.send_json(
                    "GET",
                    request_path,
                    Some((
                        String::new(),
                        None,
                        None,
                        String::new(),
                        Some(token),
                    )),
                    None,
                )
                .await?
            }
        };

        let payload: Value = serde_json::from_str(&raw).context("invalid accounts response")?;
        parse_account_snapshot(&payload)
    }

    pub async fn submit_order(
        &self,
        client_order_id: &str,
        symbol: &str,
        side: Side,
        size: f64,
        order_type: OrderType,
        planned_entry: f64,
    ) -> Result<ExchangeResult> {
        if self.dry_run {
            if size <= 0.0 || !size.is_finite() {
                return Err(anyhow!("invalid order size"));
            }
            if planned_entry <= 0.0 || !planned_entry.is_finite() {
                return Err(anyhow!("invalid planned entry"));
            }
            return Ok(ExchangeResult {
                exchange_order_id: Some(format!("dry_run_{client_order_id}")),
                executed_price: planned_entry,
                executed_size: size,
                fee: (planned_entry * size * 0.001).abs(),
                filled: true,
                raw: json!({"mode":"dry_run"}),
            });
        }

        let creds = self
            .credentials
            .as_ref()
            .context("exchange credentials are required for live mode")?;

        let planned = if planned_entry > 0.0 {
            planned_entry
        } else {
            return Err(anyhow!("invalid planned entry"));
        };

        let side_text = match side {
            Side::Buy => "BUY",
            Side::Sell => "SELL",
        };

        let mut limit_px = planned;
        if matches!(order_type, OrderType::Market) {
            // Send near-passive limit orders for deterministic behavior across endpoints.
            if side == Side::Buy {
                limit_px *= 1.002;
            } else {
                limit_px *= 0.998;
            }
        }

        let order_body = json!({
            "client_order_id": client_order_id,
            "product_id": symbol,
            "side": side_text,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": format!("{:.8}", size),
                    "limit_price": format!("{:.8}", limit_px),
                    "post_only": false,
                }
            }
        });

        let request_path = "/api/v3/brokerage/orders";
        let raw = match self.mode {
            ExchangeAuthMode::Legacy => {
                let secret_body = serde_json::to_string(&order_body)?;
                let timestamp = now_secs();
                let signature = sign_coinbase_hmac(
                    &timestamp,
                    "POST",
                    request_path,
                    &secret_body,
                    &creds.api_secret,
                )?;
                self.send_json(
                    "POST",
                    request_path,
                    Some((
                        creds.api_key.clone(),
                        Some(signature),
                        Some(timestamp),
                        creds.api_passphrase.clone().unwrap_or_default(),
                        None,
                    )),
                    Some(&secret_body),
                )
                .await?
            }
            ExchangeAuthMode::Advanced => {
                let secret_body = serde_json::to_string(&order_body)?;
                let token = sign_coinbase_advanced_jwt(
                    &creds.api_key,
                    &creds.api_secret,
                    "POST",
                    request_path,
                    &secret_body,
                )?;
                self.send_json(
                    "POST",
                    request_path,
                    Some((
                        String::new(),
                        None,
                        None,
                        String::new(),
                        Some(token),
                    )),
                    Some(&secret_body),
                )
                .await?
            }
        };

        let response_json: Value = serde_json::from_str(&raw).unwrap_or_else(|_| Value::Null);
        let envelope = serde_json::from_value::<CoinbaseOrderResponse>(response_json.clone())
            .unwrap_or_else(|_| CoinbaseOrderResponse {
                success: Some(true),
                success_response: Some(response_json.clone()),
                error: None,
                error_response: None,
                errors: None,
            });

        if envelope.success == Some(false) {
            let msg = envelope
                .error
                .or(envelope.error_response)
                .or(envelope.errors)
                .map(|value| value.to_string())
                .unwrap_or_else(|| "unknown exchange rejection".to_string());
            return Err(anyhow!("coinbase order rejected: {msg}"));
        }

        let order_id = envelope
            .success_response
            .as_ref()
            .and_then(|success| {
                success
                    .get("order_id")
                    .and_then(Value::as_str)
                    .map(std::string::ToString::to_string)
                    .or_else(||
                        success
                            .get("order")
                            .and_then(|r| r.get("order_id"))
                            .and_then(Value::as_str)
                            .map(std::string::ToString::to_string),
                    )
            })
            .or_else(||
                response_json
                    .get("order_id")
                    .and_then(Value::as_str)
                    .map(std::string::ToString::to_string),
            )
            .or_else(|| {
                response_json
                    .get("order")
                    .and_then(|r| r.get("order_id"))
                    .and_then(Value::as_str)
                    .map(std::string::ToString::to_string)
            });

        Ok(ExchangeResult {
            exchange_order_id: order_id,
            executed_price: planned,
            executed_size: size,
            fee: (planned * size * 0.001).abs(),
            filled: true,
            raw: response_json,
        })
    }

    async fn send_json(
        &self,
        method: &str,
        request_path: &str,
        headers: Option<(String, Option<String>, Option<String>, String, Option<String>)>,
        body: Option<&str>,
    ) -> Result<String> {
        let url = format!("{}{}", self.api_base_url.trim_end_matches('/'), request_path);
        let http = self.http.as_ref().context("http client not initialized")?;

        let mut req = match method {
            "POST" => http.post(url.clone()),
            "GET" => http.get(url.clone()),
            _ => return Err(anyhow!("unsupported request method: {method}")),
        }
        .header("User-Agent", "alphadb-gate/0.1");

        if let Some((api_key, hmac_signature, timestamp, passphrase, jwt)) = headers {
            match self.mode {
                ExchangeAuthMode::Legacy => {
                    req = req
                        .header("CB-ACCESS-KEY", api_key)
                        .header("CB-ACCESS-SIGN", hmac_signature.unwrap_or_default())
                        .header("CB-ACCESS-TIMESTAMP", timestamp.unwrap_or_default())
                        .header("CB-ACCESS-PASSPHRASE", passphrase);
                }
                ExchangeAuthMode::Advanced => {
                    req = req.header("Authorization", format!("Bearer {}", jwt.unwrap_or_default()));
                }
            }
        }

        if let Some(body) = body {
            req = req.header("Content-Type", "application/json").body(body.to_string());
        }

        let response = req.send().await.context("request to coinbase failed")?;
        let status = response.status();
        let raw = response.text().await.context("reading coinbase response body")?;
        if !status.is_success() {
            return Err(anyhow!("coinbase request failed status={status} body={raw}"));
        }
        Ok(raw)
    }

    async fn coinbase_get_price(&self, symbol: &str) -> Result<CoinPrice> {
        let http = self.http.as_ref().context("http client not initialized")?;

        let endpoints = [
            format!(
                "{}/api/v3/brokerage/market/products/{}/ticker",
                self.api_base_url.trim_end_matches('/'),
                symbol
            ),
            format!("{}/products/{}/ticker", self.api_base_url.trim_end_matches('/'), symbol),
        ];

        for url in &endpoints {
            let response = http.get(url).send().await;
            let response = match response {
                Ok(r) => r,
                Err(_) => continue,
            };

            if !response.status().is_success() {
                continue;
            }

            let raw = response.text().await?;
            let json: Value = match serde_json::from_str(&raw) {
                Ok(v) => v,
                Err(_) => continue,
            };
            if let Some(price) = extract_price(&json) {
                return Ok(CoinPrice {
                    price,
                    bid: extract_bid(&json),
                    ask: extract_ask(&json),
                    mark: extract_mark(&json),
                });
            }
        }

        Err(anyhow!("unable to fetch price for {symbol}"))
    }
}

fn exchange_auth_mode(exchange: &str) -> ExchangeAuthMode {
    if exchange.contains("advanced") || exchange.contains("brokerage") {
        ExchangeAuthMode::Advanced
    } else {
        ExchangeAuthMode::Legacy
    }
}

fn sign_coinbase_hmac(timestamp: &str, method: &str, request_path: &str, body: &str, secret: &str) -> Result<String> {
    let normalized_secret = normalize_base64_secret(secret);
    let decoded_secret = base64::engine::general_purpose::STANDARD
        .decode(normalized_secret)
        .with_context(|| "decode COINBASE_API_SECRET (base64)")?;

    let payload = format!("{timestamp}{method}{request_path}{body}");
    let mut mac = HmacSha256::new_from_slice(&decoded_secret).context("invalid hmac key")?;
    mac.update(payload.as_bytes());

    Ok(base64::engine::general_purpose::STANDARD.encode(mac.finalize().into_bytes()))
}

fn sign_coinbase_advanced_jwt(
    api_key: &str,
    api_secret: &str,
    method: &str,
    request_path: &str,
    _body: &str,
) -> Result<String> {
    let now = now_secs_i64();
    let claims = CoinbaseJwtClaims {
        iss: "coinbase-cloud",
        sub: api_key.to_string(),
        aud: "retail_rest_api",
        uri: format!("{method} {request_path}"),
        nbf: now - 5,
        exp: now + 60,
    };

    let mut last_err: Option<anyhow::Error> = None;
    for candidate in advanced_key_candidates(api_secret) {
        match EncodingKey::from_ec_pem(candidate.as_bytes()) {
            Ok(encoding_key) => {
                let mut header = Header::new(Algorithm::ES256);
                header.kid = Some(api_key.to_string());
                let token = encode(&header, &claims, &encoding_key)
                    .map_err(|err| anyhow!("sign advanced jwt: {err}"))?;
                return Ok(token);
            }
            Err(err) => {
                last_err = Some(anyhow!(err));
            }
        }
    }

    let base64_secret = normalize_base64_secret(api_secret);
    if let Ok(der) = base64::engine::general_purpose::STANDARD.decode(base64_secret) {
        let encoding_key = EncodingKey::from_ec_der(&der);
        let mut header = Header::new(Algorithm::ES256);
        header.kid = Some(api_key.to_string());
        let token = encode(&header, &claims, &encoding_key)
            .map_err(|err| anyhow!("sign advanced jwt: {err}"))?;
        return Ok(token);
    }

    Err(last_err.unwrap_or_else(|| anyhow!("no valid EC key candidate")).context("decode COINBASE_API_SECRET as EC private key PEM"))
}

fn advanced_key_candidates(secret: &str) -> Vec<String> {
    let mut candidates = Vec::new();
    let s = secret.trim();

    if s.contains("BEGIN") && s.contains("END") {
        candidates.push(s.to_string());
    }

    candidates.push(normalize_advanced_secret(secret));
    candidates.push(format!(
        "-----BEGIN PRIVATE KEY-----\n{}\n-----END PRIVATE KEY-----\n",
        normalize_base64_secret(secret)
    ));
    candidates
}

fn normalize_base64_secret(secret: &str) -> String {
    let mut out = String::new();
    for line in secret.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("-----BEGIN") || trimmed.starts_with("-----END") {
            continue;
        }
        out.push_str(trimmed);
    }

    if !out.is_empty() {
        return out;
    }

    let mut body = secret.to_string();
    for marker in [
        "-----BEGIN EC PRIVATE KEY-----",
        "-----END EC PRIVATE KEY-----",
        "-----BEGIN PRIVATE KEY-----",
        "-----END PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----END RSA PRIVATE KEY-----",
    ] {
        body = body.replace(marker, "");
    }

    body.chars().filter(|c| !c.is_whitespace()).collect()
}

fn normalize_advanced_secret(secret: &str) -> String {
    let s = secret.trim();
    if s.contains("BEGIN") && s.contains("END") {
        let begin_markers = [
            "-----BEGIN EC PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
        ];
        let end_markers = [
            "-----END EC PRIVATE KEY-----",
            "-----END PRIVATE KEY-----",
            "-----END RSA PRIVATE KEY-----",
        ];

        let mut selected_body: Option<String> = None;
        for (begin, end) in begin_markers.iter().zip(end_markers.iter()) {
            if let (Some(start_idx), Some(end_idx)) = (s.find(begin), s.find(end)) {
                if start_idx < end_idx {
                    let body = s[start_idx + begin.len()..end_idx]
                        .chars()
                        .filter(|c| !c.is_whitespace())
                        .collect::<String>();
                    if !body.is_empty() {
                        selected_body = Some(body);
                        break;
                    }
                }
            }
        }

        if let Some(body) = selected_body {
            let mut out = String::new();
            out.push_str("-----BEGIN EC PRIVATE KEY-----\n");
            let mut idx = 0;
            while idx < body.len() {
                let end = (idx + 64).min(body.len());
                out.push_str(&body[idx..end]);
                out.push('\n');
                idx = end;
            }
            out.push_str("-----END EC PRIVATE KEY-----\n");
            out
        } else {
            s.to_string()
        }
    } else {
        s.to_string()
    }
}

fn as_f64(value: &Value) -> Option<f64> {
    match value {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.parse::<f64>().ok(),
        _ => None,
    }
}

fn extract_price(v: &Value) -> Option<f64> {
    v.get("price")
        .and_then(as_f64)
        .or_else(|| v.get("mark").and_then(as_f64))
        .or_else(|| {
            let bid = v.get("best_bid").and_then(as_f64)?;
            let ask = v.get("best_ask").and_then(as_f64)?;
            Some((bid + ask) / 2.0)
        })
}

fn extract_bid(v: &Value) -> Option<f64> {
    v.get("bid").and_then(as_f64).or_else(|| v.get("best_bid").and_then(as_f64))
}

fn extract_ask(v: &Value) -> Option<f64> {
    v.get("ask").and_then(as_f64).or_else(|| v.get("best_ask").and_then(as_f64))
}

fn extract_mark(v: &Value) -> Option<f64> {
    v.get("mark_price").and_then(as_f64).or_else(|| v.get("mark").and_then(as_f64))
}

fn parse_account_snapshot(json: &Value) -> Result<CoinBaseAccountSnapshot> {
    if let Some(error) = json.get("error") {
        return Err(anyhow!("account endpoint error: {error}"));
    }

    let mut available_cash: Option<f64> = None;
    let mut account_value: Option<f64> = None;
    let mut currency: Option<String> = None;

    if let Some(accounts) = json.get("accounts").and_then(Value::as_array) {
        for account in accounts {
            let account_currency = account
                .get("currency")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_ascii_uppercase();

            let preferred_currency = matches!(account_currency.as_str(), "USD" | "USDC" | "USDT");
            if preferred_currency {
                currency = currency.or_else(|| Some(account_currency.clone()));
            }

            update_account_totals(
                account,
                preferred_currency || currency.is_none(),
                &mut available_cash,
                &mut account_value,
            );
        }
    }

    if available_cash.is_none() || account_value.is_none() {
        if let Some(accounts) = json.get("data").and_then(Value::as_array) {
            for account in accounts {
                update_account_totals(
                    account,
                    true,
                    &mut available_cash,
                    &mut account_value,
                );
            }
        }
    }

    if available_cash.is_none() {
        available_cash = json
            .get("available_balance")
            .and_then(extract_money)
            .or_else(|| {
                json.get("account")
                    .and_then(|account| account.get("available_balance").and_then(extract_money))
            })
            .or_else(|| json.get("available_cash").and_then(extract_money));
    }

    if account_value.is_none() {
        account_value = json
            .get("balance")
            .and_then(extract_money)
            .or_else(|| json.get("account_value").and_then(extract_money))
            .or_else(|| json.get("available_balance").and_then(extract_money));
    }

    let available_cash = available_cash.unwrap_or(0.0);
    let account_value = account_value.unwrap_or(available_cash);

    if available_cash == 0.0 && account_value == 0.0 {
        return Err(anyhow!("no balances returned in accounts response"));
    }

    Ok(CoinBaseAccountSnapshot {
        available_cash,
        account_value,
        currency,
    })
}

fn update_account_totals(
    account: &Value,
    accept_any_currency: bool,
    available_cash: &mut Option<f64>,
    account_value: &mut Option<f64>,
) {
    if available_cash.is_none() {
        *available_cash = extract_account_money(account, "available_balance")
            .or_else(|| account.get("available_cash").and_then(extract_money))
            .or_else(|| account.get("cash").and_then(extract_money));
    }

    if account_value.is_none() && (accept_any_currency || account
        .get("currency")
        .and_then(Value::as_str)
        .map(|c| matches!(c.to_ascii_uppercase().as_str(), "USD" | "USDC" | "USDT"))
        .unwrap_or(false))
    {
        *account_value = account
            .get("total_balance")
            .and_then(extract_money)
            .or_else(|| extract_account_money(account, "balance"))
            .or_else(|| extract_account_money(account, "account_value"))
            .or_else(|| extract_account_money(account, "available_balance"));
    }
}

fn extract_account_money(account: &Value, key: &str) -> Option<f64> {
    account.get(key).and_then(extract_money)
}

fn extract_money(value: &Value) -> Option<f64> {
    match value {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.parse::<f64>().ok(),
        Value::Object(obj) => obj.get("value").and_then(extract_money),
        _ => None,
    }
}

fn now_secs() -> String {
    now_secs_i64().to_string()
}

fn now_secs_i64() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or_else(|_| 0)
}

#[cfg(test)]
mod tests {
    use super::exchange_auth_mode;

    #[test]
    fn test_price_extract() {
        let v = serde_json::json!({"price":"123.45", "bid":"122", "ask":"124"});
        assert!((super::extract_price(&v).unwrap() - 123.45).abs() < 1e-9);
        assert_eq!(super::exchange_auth_mode("coinbase_advanced"), super::ExchangeAuthMode::Advanced);
        assert_eq!(super::exchange_auth_mode("coinbase"), super::ExchangeAuthMode::Legacy);
    }
}
