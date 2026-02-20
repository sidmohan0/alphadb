use anyhow::{Context, Result};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixStream;
use trading_common::{GateRequest, GateResponse};

#[derive(Clone)]
pub struct GateClient {
    socket: String,
}

impl GateClient {
    pub fn new(socket: impl Into<String>) -> Self {
        Self { socket: socket.into() }
    }

    pub async fn send(&self, request: &GateRequest) -> Result<GateResponse> {
        let mut stream = UnixStream::connect(&self.socket)
            .await
            .with_context(|| format!("connecting to gate socket {}", self.socket))?;

        let payload = serde_json::to_string(request)?;
        stream.write_all(payload.as_bytes()).await?;
        stream.write_all(b"\n").await?;

        let mut reader = BufReader::new(stream);
        let mut response_line = String::new();
        reader.read_line(&mut response_line).await?;
        if response_line.trim().is_empty() {
            return Err(anyhow::anyhow!("empty response"));
        }

        let response: GateResponse = serde_json::from_str(response_line.trim())
            .with_context(|| format!("parsing response: {response_line}"))?;
        Ok(response)
    }
}
