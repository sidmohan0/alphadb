use anyhow::Result;
use chrono::Utc;
use std::fs::{self, OpenOptions};
use std::io::Write;
use serde_json::json;

pub struct AuditLog {
    path: String,
}

impl AuditLog {
    pub fn new(path: &str) -> Self {
        let _ = fs::create_dir_all(std::path::Path::new(path).parent().unwrap_or_else(|| std::path::Path::new(".")));
        Self { path: path.to_string() }
    }

    pub fn log_submit_decision(
        &self,
        _req: &trading_common::GateRequest,
        checks: &[trading_common::CheckResult],
        accepted: bool,
        order_id: Option<String>,
    ) -> Result<()> {
        let payload = json!({
            "timestamp": Utc::now().to_rfc3339(),
            "request_type": "SubmitOrder",
            "accepted": accepted,
            "order_id": order_id.unwrap_or_else(|| "pending".to_string()),
            "checks": checks,
        });
        self.append(&payload.to_string())
    }

    pub fn log_proposal(&self, proposal_id: &str, auto_approved: bool, reason: &str) -> Result<()> {
        let payload = json!({
            "timestamp": Utc::now().to_rfc3339(),
            "request_type": "ProposeRule",
            "proposal_id": proposal_id,
            "auto_approved": auto_approved,
            "reason": reason,
        });
        self.append(&payload.to_string())
    }

    fn append(&self, line: &str) -> Result<()> {
        let mut f = OpenOptions::new().create(true).append(true).open(&self.path)?;
        writeln!(f, "{}", line)?;
        Ok(())
    }
}
