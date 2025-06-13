use crate::model::Trade;
use std::time::Duration;
use tokio::time::{interval, Instant};
use tracing::{debug, info, warn};

pub struct TradeBuffer {
    buffer: Vec<Trade>,
    max_rows: usize,
    max_duration: Duration,
    last_flush: Instant,
}

impl TradeBuffer {
    pub fn new(max_rows: usize, max_duration_ms: u64) -> Self {
        Self {
            buffer: Vec::with_capacity(max_rows),
            max_rows,
            max_duration: Duration::from_millis(max_duration_ms),
            last_flush: Instant::now(),
        }
    }

    pub fn add_trade(&mut self, trade: Trade) -> bool {
        self.buffer.push(trade);
        self.should_flush()
    }

    pub fn should_flush(&self) -> bool {
        self.buffer.len() >= self.max_rows || 
        self.last_flush.elapsed() >= self.max_duration
    }

    pub fn flush(&mut self) -> Vec<Trade> {
        let trades = std::mem::take(&mut self.buffer);
        self.last_flush = Instant::now();
        self.buffer = Vec::with_capacity(self.max_rows);
        trades
    }

    pub fn len(&self) -> usize {
        self.buffer.len()
    }

    pub fn is_empty(&self) -> bool {
        self.buffer.is_empty()
    }
}

pub struct BatchProcessor {
    buffer: TradeBuffer,
    trade_receiver: tokio::sync::mpsc::UnboundedReceiver<Trade>,
    db_sender: tokio::sync::mpsc::UnboundedSender<Vec<Trade>>,
}

impl BatchProcessor {
    pub fn new(
        max_rows: usize,
        max_duration_ms: u64,
        trade_receiver: tokio::sync::mpsc::UnboundedReceiver<Trade>,
        db_sender: tokio::sync::mpsc::UnboundedSender<Vec<Trade>>,
    ) -> Self {
        Self {
            buffer: TradeBuffer::new(max_rows, max_duration_ms),
            trade_receiver,
            db_sender,
        }
    }

    pub async fn run(mut self) {
        let mut flush_interval = interval(Duration::from_millis(100)); // Check every 100ms
        flush_interval.tick().await; // Skip first immediate tick

        loop {
            tokio::select! {
                // Receive trades from WebSocket
                trade_opt = self.trade_receiver.recv() => {
                    match trade_opt {
                        Some(trade) => {
                            debug!("Buffering trade: {} {} @ {}", 
                                   trade.symbol, trade.side, trade.price);
                            
                            if self.buffer.add_trade(trade) {
                                self.flush_buffer().await;
                            }
                        }
                        None => {
                            info!("Trade receiver closed, flushing remaining buffer");
                            if !self.buffer.is_empty() {
                                self.flush_buffer().await;
                            }
                            break;
                        }
                    }
                }
                
                // Periodic flush check
                _ = flush_interval.tick() => {
                    if self.buffer.should_flush() && !self.buffer.is_empty() {
                        self.flush_buffer().await;
                    }
                }
            }
        }
    }

    async fn flush_buffer(&mut self) {
        let trades = self.buffer.flush();
        let trade_count = trades.len();
        
        if trade_count > 0 {
            info!("Flushing {} trades to database", trade_count);
            
            if let Err(_) = self.db_sender.send(trades) {
                warn!("Database sender channel closed");
            }
        }
    }
}