use anyhow::{Context, Result};
use std::{fs, path::Path};
use trading_common::SafetyConfig;

#[derive(Clone)]
pub struct GateConfig {
    pub safety: SafetyConfig,
}

impl GateConfig {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let content = fs::read_to_string(&path)
            .with_context(|| format!("reading safety config at {:?}", path.as_ref()))?;
        let safety: SafetyConfig = serde_yaml::from_str(&content)
            .with_context(|| "parsing safety config (YAML)")?;
        Ok(Self { safety })
    }
}
