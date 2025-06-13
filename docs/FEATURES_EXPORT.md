# 📊 AlphaDB Features Export Guide

Transform your real-time TimescaleDB features into ML/backtesting-ready datasets.

## 🚀 Quick Start

```bash
# Export last 24 hours for ML training
python scripts/export_features.py --incremental --hours 24

# Export VectorBT-ready OHLCV + features  
python scripts/export_features.py --vectorbt --symbols BTC/USDT --days 30

# Export ML-ready features with targets and engineered features
python scripts/export_features.py --ml-ready --days 90
```

## 📋 Export Options

### 1. **Basic Features Export**
```bash
# Historical backfill (last 90 days)
python scripts/export_features.py --backfill --days 90

# Recent data only (last 6 hours)  
python scripts/export_features.py --incremental --hours 6

# Specific symbols
python scripts/export_features.py --backfill --symbols BTC/USDT ETH/USDT --days 30
```

**Output**: Raw features from TimescaleDB → `features_SYMBOL_DATE.parquet`

### 2. **VectorBT-Ready Export**
```bash
# Perfect for backtesting with VectorBT
python scripts/export_features.py --vectorbt --symbols BTC/USDT --days 60
```

**Output**: OHLCV + features with timestamp index → `vectorbt_SYMBOL_60d.parquet`

### 3. **ML-Ready Export**
```bash
# Full feature engineering pipeline
python scripts/export_features.py --ml-ready --symbols BTC/USDT ETH/USDT --days 30
```

**Output**: Enhanced features with targets → `ml_features_SYMBOL_30d.parquet`

**Includes:**
- ✅ Lagged features (1m, 5m, 15m, 1h)  
- ✅ Rolling statistics (MA, std dev)
- ✅ Return calculations  
- ✅ Volatility regimes
- ✅ Target variables (1m, 5m, 15m future returns)

## 🐍 Python Usage

```python
from scripts.export_features import FeaturesExporter

# Initialize exporter
exporter = FeaturesExporter(output_dir="my_data")

# Quick VectorBT export
vbt_file = exporter.export_vectorbt_ready('BTC/USDT', days=90)

# Load for analysis
import pandas as pd
df = pd.read_parquet(vbt_file)
print(f"Data shape: {df.shape}")
```

## 📊 Use Cases

### 🤖 **Machine Learning**
```python
# Load ML-ready features
df = pd.read_parquet('data/features/ml_features_BTCUSDT_30d.parquet')

# Prepare for sklearn
features = [col for col in df.columns if not col.startswith('target_')]
X = df[features].dropna()
y = df['target_5m_sign'].dropna()  # 5-minute direction prediction

# Train model
from sklearn.ensemble import RandomForestClassifier
rf = RandomForestClassifier().fit(X, y)
```

### 📈 **VectorBT Backtesting**
```python
import vectorbt as vbt
import pandas as pd

# Load VectorBT data
df = pd.read_parquet('data/features/vectorbt_BTCUSDT_90d.parquet')

# Create strategy signals
signals = (df['hl_range_pct'] > df['hl_range_pct'].rolling(60).mean()) & (df['vwap_gap'] > 0)

# Backtest
portfolio = vbt.Portfolio.from_signals(df['close'], signals, ~signals, fees=0.001)
print(f"Return: {portfolio.total_return():.2%}")
```

### 📊 **Data Analysis**
```python
# Load and analyze features
df = pd.read_parquet('data/features/features_BTCUSDT-ETHUSDT_20250613_to_all.parquet')

# Compare symbols
btc_vol = df[df.symbol == 'BTC/USDT']['hl_range_pct'].mean()
eth_vol = df[df.symbol == 'ETH/USDT']['hl_range_pct'].mean()

print(f"BTC avg volatility: {btc_vol*100:.3f}%")
print(f"ETH avg volatility: {eth_vol*100:.3f}%")
```

## 🗂️ File Formats

### Raw Features (`features_*.parquet`)
```
bucket | symbol | open_price | high_price | low_price | close_price | volume | hl_range_pct | vwap_gap | parkinson_vol | is_green
```

### VectorBT Format (`vectorbt_*.parquet`) 
```
timestamp (index) | open | high | low | close | volume | hl_range_pct | vwap_gap | parkinson_vol | is_green
```

### ML Features (`ml_features_*.parquet`)
```
bucket | symbol | [base_features] | [lagged_features] | [rolling_features] | [targets] | vol_regime
```

## ⚙️ Configuration

### Database Connection
```bash
# Default: postgresql://trader:s3cr3t@localhost:5432/market
export DATABASE_URL="postgresql://user:pass@host:port/database"

# Or specify directly
python scripts/export_features.py --db-url "postgresql://..." --backfill
```

### Output Directory
```bash
# Default: data/features/
python scripts/export_features.py --output-dir "/path/to/exports" --backfill
```

## 📈 Production Workflows

### Daily Data Pipeline
```bash
#!/bin/bash
# daily_export.sh

# Export yesterday's data for analysis
python scripts/export_features.py --incremental --hours 24

# Update VectorBT files weekly (Sunday)
if [ $(date +%u) -eq 7 ]; then
    python scripts/export_features.py --vectorbt --days 90
fi

# Retrain ML models monthly
if [ $(date +%d) -eq 01 ]; then
    python scripts/export_features.py --ml-ready --days 30
fi
```

### Cron Schedule
```cron
# Export features every 6 hours
0 */6 * * * cd /path/to/alphadb && python scripts/export_features.py --incremental --hours 6

# Weekly VectorBT refresh
0 2 * * 0 cd /path/to/alphadb && python scripts/export_features.py --vectorbt --days 90  

# Monthly ML dataset
0 3 1 * * cd /path/to/alphadb && python scripts/export_features.py --ml-ready --days 60
```

## 🔧 Advanced Usage

### Custom Feature Export
```python
from scripts.export_features import FeaturesExporter
from datetime import datetime, timedelta

exporter = FeaturesExporter()

# Export specific date range
start = datetime(2025, 6, 1)
end = datetime(2025, 6, 13)

filepath = exporter.export_features(
    symbols=['BTC/USDT'],
    start_date=start,
    end_date=end
)
```

### Batch Export Multiple Symbols
```python
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
for symbol in symbols:
    exporter.export_vectorbt_ready(symbol, days=90)
```

## 📋 Metadata & Validation

Each export includes a JSON metadata file:
```json
{
  "export_timestamp": "2025-06-13T15:08:01.657",
  "total_records": 173,
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "date_range": {
    "start": "2025-06-13T19:06:00+00:00",
    "end": "2025-06-13T22:05:00+00:00"
  },
  "file_size_mb": 0.02
}
```

## 🎯 What's Next?

Your AlphaDB features are now export-ready! You can:

1. **🤖 Train ML models** with the engineered features
2. **📈 Backtest strategies** using VectorBT 
3. **📊 Analyze market patterns** with pandas/jupyter
4. **🚀 Deploy real-time trading** systems
5. **☁️ Scale to cloud** infrastructure

Happy trading! 📊🚀