use crate::model::{parse_kraken_message, Trade};
use crate::config::ExchangeConfig;
use anyhow::{Result, anyhow};
use futures_util::{SinkExt, StreamExt};
use serde_json::json;
use std::time::Duration;
use tokio::time::{interval, sleep};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{info, warn, error, debug};
use url::Url;

pub struct WebSocketClient {
    config: ExchangeConfig,
    trade_sender: tokio::sync::mpsc::UnboundedSender<Trade>,
}

impl WebSocketClient {
    pub fn new(
        config: ExchangeConfig,
        trade_sender: tokio::sync::mpsc::UnboundedSender<Trade>,
    ) -> Self {
        Self {
            config,
            trade_sender,
        }
    }

    pub async fn run(&self) -> Result<()> {
        let mut reconnect_delay = Duration::from_secs(1);
        let max_delay = Duration::from_secs(30);

        loop {
            match self.connect_and_run().await {
                Ok(_) => {
                    info!("WebSocket connection ended normally");
                    reconnect_delay = Duration::from_secs(1); // Reset delay on successful connection
                }
                Err(e) => {
                    error!("WebSocket error: {}", e);
                    warn!("Reconnecting in {:?}", reconnect_delay);
                    sleep(reconnect_delay).await;
                    
                    // Exponential backoff
                    reconnect_delay = std::cmp::min(reconnect_delay * 2, max_delay);
                }
            }
        }
    }

    async fn connect_and_run(&self) -> Result<()> {
        info!("Connecting to {} for venue {}", self.config.ws_url, self.config.venue);
        
        let url = Url::parse(&self.config.ws_url)?;
        let (ws_stream, _) = connect_async(url).await?;
        let (mut write, mut read) = ws_stream.split();

        info!("Connected to WebSocket, subscribing to trades for pairs: {:?}", self.config.pairs);

        // Subscribe to trade feeds for all pairs
        for pair in &self.config.pairs {
            let subscription = json!({
                "event": "subscribe",
                "pair": [pair],
                "subscription": {
                    "name": "trade"
                }
            });
            
            let sub_msg = Message::Text(subscription.to_string());
            write.send(sub_msg).await?;
            debug!("Sent subscription for pair: {}", pair);
        }

        // Set up heartbeat/ping interval
        let mut ping_interval = interval(Duration::from_secs(15));
        ping_interval.tick().await; // Skip first immediate tick

        loop {
            tokio::select! {
                // Handle incoming messages
                msg = read.next() => {
                    match msg {
                        Some(Ok(Message::Text(text))) => {
                            self.handle_message(&text).await?;
                        }
                        Some(Ok(Message::Pong(_))) => {
                            debug!("Received pong");
                        }
                        Some(Ok(Message::Close(_))) => {
                            warn!("WebSocket closed by server");
                            return Err(anyhow!("WebSocket closed"));
                        }
                        Some(Err(e)) => {
                            error!("WebSocket error: {}", e);
                            return Err(e.into());
                        }
                        None => {
                            warn!("WebSocket stream ended");
                            return Err(anyhow!("Stream ended"));
                        }
                        _ => {
                            debug!("Received non-text message");
                        }
                    }
                }
                
                // Send periodic pings
                _ = ping_interval.tick() => {
                    debug!("Sending ping");
                    if let Err(e) = write.send(Message::Ping(vec![])).await {
                        error!("Failed to send ping: {}", e);
                        return Err(e.into());
                    }
                }
            }
        }
    }

    async fn handle_message(&self, text: &str) -> Result<()> {
        debug!("Received message: {}", text);

        // Check for subscription confirmations
        if text.contains("\"event\":\"subscriptionStatus\"") {
            if text.contains("\"status\":\"subscribed\"") {
                info!("Successfully subscribed to trade feed");
            } else if text.contains("\"status\":\"error\"") {
                error!("Subscription error: {}", text);
                return Err(anyhow!("Subscription failed"));
            }
            return Ok(());
        }

        // Check for heartbeat
        if text.contains("\"event\":\"heartbeat\"") {
            debug!("Received heartbeat");
            return Ok(());
        }

        // Parse trade messages
        match parse_kraken_message(text, &self.config.venue) {
            Ok(trades) => {
                for trade in trades {
                    metrics::counter!("ws_msgs_total", "symbol" => trade.symbol.clone()).increment(1);
                    
                    // Calculate ingestion lag
                    let lag_ms = (trade.ts_ingest - trade.ts_exchange).num_milliseconds();
                    metrics::histogram!("ws_lag_ms").record(lag_ms as f64);
                    
                    debug!("Parsed trade: {} {} @ {} ({})", 
                           trade.symbol, trade.side, trade.price, trade.qty);
                    
                    if self.trade_sender.send(trade).is_err() {
                        warn!("Trade channel full, dropping connection due to back-pressure");
                        return Err(anyhow!("Back-pressure detected"));
                    }
                }
            }
            Err(e) => {
                warn!("Failed to parse message: {} - Error: {}", text, e);
            }
        }

        Ok(())
    }
}

// Helper function to check if buffer is approaching capacity
pub fn is_buffer_full(sender: &tokio::sync::mpsc::UnboundedSender<Trade>) -> bool {
    // This is a heuristic - in practice you might want to use a bounded channel
    // and check its capacity directly
    sender.is_closed()
}