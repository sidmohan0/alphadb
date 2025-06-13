use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use anyhow::{Result, anyhow};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trade {
    pub ts_exchange: DateTime<Utc>,
    pub ts_ingest: DateTime<Utc>,
    pub venue: String,
    pub symbol: String,
    pub side: TradeSide,
    pub price: Decimal,
    pub qty: Decimal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TradeSide {
    Buy,
    Sell,
}

impl std::fmt::Display for TradeSide {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TradeSide::Buy => write!(f, "buy"),
            TradeSide::Sell => write!(f, "sell"),
        }
    }
}

// Kraken WebSocket message structures
#[derive(Debug, Deserialize)]
pub struct KrakenWsMessage {
    #[serde(flatten)]
    pub content: KrakenMessageContent,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum KrakenMessageContent {
    Trade(Vec<serde_json::Value>),
    Subscription(KrakenSubscriptionResponse),
    Heartbeat(KrakenHeartbeat),
}

#[derive(Debug, Deserialize)]
pub struct KrakenSubscriptionResponse {
    #[serde(rename = "channelID")]
    pub channel_id: Option<u64>,
    #[serde(rename = "channelName")]
    pub channel_name: Option<String>,
    pub event: String,
    pub pair: Option<String>,
    pub status: Option<String>,
    pub subscription: Option<KrakenSubscription>,
}

#[derive(Debug, Deserialize)]
pub struct KrakenSubscription {
    pub name: String,
}

#[derive(Debug, Deserialize)]
pub struct KrakenHeartbeat {
    pub event: String,
}

#[derive(Debug, Deserialize)]
pub struct KrakenTradeData {
    pub price: String,
    pub volume: String,
    pub time: String,
    pub side: String,
    pub order_type: String,
    pub misc: String,
}

impl Trade {
    pub fn from_kraken_trade(
        trade_data: &KrakenTradeData,
        symbol: &str,
        venue: &str,
    ) -> Result<Self> {
        let price = trade_data.price.parse::<Decimal>()
            .map_err(|_| anyhow!("Invalid price: {}", trade_data.price))?;
        
        let qty = trade_data.volume.parse::<Decimal>()
            .map_err(|_| anyhow!("Invalid volume: {}", trade_data.volume))?;
        
        if price <= Decimal::ZERO {
            return Err(anyhow!("Price must be positive: {}", price));
        }
        
        if qty <= Decimal::ZERO {
            return Err(anyhow!("Quantity must be positive: {}", qty));
        }
        
        let side = match trade_data.side.as_str() {
            "b" => TradeSide::Buy,
            "s" => TradeSide::Sell,
            _ => return Err(anyhow!("Invalid side: {}", trade_data.side)),
        };
        
        let ts_exchange = DateTime::parse_from_str(&trade_data.time, "%s%.f")
            .map_err(|_| anyhow!("Invalid timestamp: {}", trade_data.time))?
            .with_timezone(&Utc);
        
        Ok(Trade {
            ts_exchange,
            ts_ingest: Utc::now(),
            venue: venue.to_string(),
            symbol: symbol.to_string(),
            side,
            price,
            qty,
        })
    }
}

pub fn parse_kraken_message(msg: &str, venue: &str) -> Result<Vec<Trade>> {
    let raw_value: serde_json::Value = serde_json::from_str(msg)?;
    
    // Skip non-array messages (subscriptions, heartbeats, etc.)
    let array = match raw_value.as_array() {
        Some(arr) => arr,
        None => return Ok(vec![]),
    };
    
    // Kraken trade messages: [channel_id, trade_data, "trade", "pair"]
    if array.len() != 4 {
        return Ok(vec![]);
    }
    
    let channel_name = array[2].as_str().unwrap_or("");
    if channel_name != "trade" {
        return Ok(vec![]);
    }
    
    let pair = array[3].as_str().unwrap_or("");
    let trade_data = &array[1];
    
    let mut trades = Vec::new();
    
    if let Some(trade_array) = trade_data.as_array() {
        for trade_item in trade_array {
            if let Some(trade_details) = trade_item.as_array() {
                if trade_details.len() >= 6 {
                    let kraken_trade = KrakenTradeData {
                        price: trade_details[0].as_str().unwrap_or("0").to_string(),
                        volume: trade_details[1].as_str().unwrap_or("0").to_string(),
                        time: trade_details[2].as_str().unwrap_or("0").to_string(),
                        side: trade_details[3].as_str().unwrap_or("").to_string(),
                        order_type: trade_details[4].as_str().unwrap_or("").to_string(),
                        misc: trade_details[5].as_str().unwrap_or("").to_string(),
                    };
                    
                    if let Ok(trade) = Trade::from_kraken_trade(&kraken_trade, pair, venue) {
                        trades.push(trade);
                    }
                }
            }
        }
    }
    
    Ok(trades)
}