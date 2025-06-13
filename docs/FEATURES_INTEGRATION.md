# Features Integration Guide 🧠

Your AlphaDB now includes **real-time feature engineering** with continuous aggregates that auto-refresh every minute. This guide shows you how to use the features in your ML pipelines.

## 🎯 Available Features

### Core Features
- **OHLCV Data**: `open_price`, `high_price`, `low_price`, `close_price`, `volume`
- **Range Metrics**: `hl_range`, `hl_range_pct` (volatility proxy)
- **Body Metrics**: `body_size`, `body_pct` (momentum proxy)
- **VWAP Gap**: `vwap_gap` (price vs weighted average)
- **Volatility**: `parkinson_vol` (Parkinson estimator)
- **Position**: `price_position` (where close sits in high-low range)
- **Patterns**: `is_green`, `is_doji` (candlestick classification)

### Data Availability
- **Symbols**: BTC/USDT, ETH/USDT
- **Granularity**: 1-minute bars
- **Auto-refresh**: Every minute
- **History**: 90+ days available

## 📊 Quick Usage Examples

### 1. Latest Features (Real-time)
```sql
-- Get latest feature values for both symbols
SELECT * FROM features_1m 
ORDER BY bucket DESC 
LIMIT 4;
```

### 2. Historical Range Query
```sql
-- Get features for specific time range
SELECT bucket, symbol, close_price, hl_range_pct, parkinson_vol
FROM features_1m 
WHERE bucket BETWEEN '2025-06-01' AND '2025-06-13'
  AND symbol = 'BTC/USDT'
ORDER BY bucket;
```

### 3. High Volatility Periods
```sql
-- Find high volatility periods
SELECT bucket, symbol, hl_range_pct, parkinson_vol
FROM features_1m 
WHERE hl_range_pct > 0.001  -- 0.1% moves
ORDER BY hl_range_pct DESC 
LIMIT 20;
```

## 🐍 Python Integration

### Basic Data Loading
```python
import pandas as pd
from sqlalchemy import create_engine

# Database connection
engine = create_engine("postgresql://trader:s3cr3t@localhost:5432/market")

def get_features(symbol='BTC/USDT', hours=24):
    """Load recent features for a symbol"""
    sql = """
    SELECT bucket, close_price, hl_range_pct, vwap_gap, 
           parkinson_vol, is_green, volume
    FROM features_1m 
    WHERE symbol = %s 
      AND bucket >= NOW() - INTERVAL %s
    ORDER BY bucket
    """
    return pd.read_sql(sql, engine, params=[symbol, f'{hours} hours'])

# Load last 24 hours of BTC features
btc_features = get_features('BTC/USDT', 24)
print(f"Loaded {len(btc_features)} BTC feature records")
```

### Multi-Symbol Analysis
```python
def get_multi_symbol_features(symbols=['BTC/USDT', 'ETH/USDT'], days=7):
    """Load features for multiple symbols"""
    placeholders = ','.join(['%s'] * len(symbols))
    sql = f"""
    SELECT bucket, symbol, close_price, hl_range_pct, 
           parkinson_vol, vwap_gap, is_green
    FROM features_1m 
    WHERE symbol IN ({placeholders})
      AND bucket >= NOW() - INTERVAL %s
    ORDER BY symbol, bucket
    """
    return pd.read_sql(sql, engine, params=symbols + [f'{days} days'])

# Load weekly data for both symbols
multi_data = get_multi_symbol_features(['BTC/USDT', 'ETH/USDT'], 7)
```

### Feature Engineering Pipeline
```python
def create_ml_features(df):
    """Add derived features for ML"""
    df = df.copy()
    
    # Sort by time for each symbol
    df = df.sort_values(['symbol', 'bucket'])
    
    # Add lagged features
    for lag in [1, 5, 15]:
        df[f'close_lag_{lag}'] = df.groupby('symbol')['close_price'].shift(lag)
        df[f'vol_lag_{lag}'] = df.groupby('symbol')['parkinson_vol'].shift(lag)
    
    # Add rolling features (using TimescaleDB features as base)
    for window in [5, 15, 60]:
        df[f'hl_range_ma_{window}'] = df.groupby('symbol')['hl_range_pct'].rolling(window).mean().values
        df[f'vwap_gap_ma_{window}'] = df.groupby('symbol')['vwap_gap'].rolling(window).mean().values
    
    # Add target (future returns)
    df['target_1m'] = df.groupby('symbol')['close_price'].pct_change(1).shift(-1)
    df['target_5m'] = df.groupby('symbol')['close_price'].pct_change(5).shift(-5)
    
    return df

# Apply feature engineering
features_df = get_multi_symbol_features(['BTC/USDT'], 30)  # 30 days
ml_features = create_ml_features(features_df)

print(f"Created {len(ml_features.columns)} features for ML")
```

## 📈 VectorBT Integration

```python
import vectorbt as vbt
import numpy as np

def backtest_strategy_with_features():
    """Example backtest using AlphaDB features"""
    
    # Load features
    sql = """
    SELECT bucket as timestamp, symbol, close_price, 
           hl_range_pct, parkinson_vol, vwap_gap
    FROM features_1m 
    WHERE symbol = 'BTC/USDT'
      AND bucket >= '2025-05-01'
    ORDER BY bucket
    """
    df = pd.read_sql(sql, engine)
    df.set_index('timestamp', inplace=True)
    
    # Create signals based on volatility and VWAP gap
    signals = (
        (df['hl_range_pct'] > df['hl_range_pct'].rolling(60).mean()) &  # High volatility
        (df['vwap_gap'] > 0) &  # Price above VWAP
        (df['parkinson_vol'] > df['parkinson_vol'].rolling(60).quantile(0.7))  # High Parkinson vol
    )
    
    # Run backtest
    portfolio = vbt.Portfolio.from_signals(
        df['close_price'], 
        signals, 
        ~signals,  # Exit when signal is false
        fees=0.001,  # 0.1% fees
        freq='1T'  # 1-minute frequency
    )
    
    return portfolio

# Run backtest
portfolio = backtest_strategy_with_features()
print(f"Total return: {portfolio.total_return():.2%}")
print(f"Sharpe ratio: {portfolio.sharpe_ratio():.2f}")
```

## ⚡ FastAPI Real-time Features

```python
from fastapi import FastAPI
import asyncio
import asyncpg

app = FastAPI()

async def get_db_connection():
    return await asyncpg.connect(
        "postgresql://trader:s3cr3t@localhost:5432/market"
    )

@app.get("/features/latest/{symbol}")
async def get_latest_features(symbol: str):
    """Get latest features for a symbol"""
    conn = await get_db_connection()
    
    query = """
    SELECT bucket, close_price, hl_range_pct, vwap_gap,
           parkinson_vol, is_green, volume
    FROM features_1m 
    WHERE symbol = $1
    ORDER BY bucket DESC 
    LIMIT 1
    """
    
    row = await conn.fetchrow(query, symbol)
    await conn.close()
    
    if row:
        return dict(row)
    else:
        return {"error": "No data found"}

@app.get("/features/signals/{symbol}")
async def get_trading_signals(symbol: str, lookback_minutes: int = 60):
    """Generate trading signals based on features"""
    conn = await get_db_connection()
    
    query = """
    SELECT bucket, close_price, hl_range_pct, vwap_gap, parkinson_vol,
           AVG(hl_range_pct) OVER (ORDER BY bucket ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) as vol_ma,
           AVG(vwap_gap) OVER (ORDER BY bucket ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as vwap_ma
    FROM features_1m 
    WHERE symbol = $1
      AND bucket >= NOW() - INTERVAL '2 hours'
    ORDER BY bucket DESC
    LIMIT $2
    """
    
    rows = await conn.fetch(query, symbol, lookback_minutes)
    await conn.close()
    
    signals = []
    for row in rows:
        # Simple momentum signal
        signal = {
            "timestamp": row['bucket'],
            "price": row['close_price'],
            "buy_signal": row['vwap_gap'] > row['vwap_ma'] and row['hl_range_pct'] > row['vol_ma'],
            "sell_signal": row['vwap_gap'] < row['vwap_ma'] and row['hl_range_pct'] < row['vol_ma'],
            "volatility_regime": "high" if row['hl_range_pct'] > row['vol_ma'] else "low"
        }
        signals.append(signal)
    
    return {"symbol": symbol, "signals": signals[:10]}  # Return latest 10
```

## 📊 Grafana Integration

### Feature Monitoring Dashboard

Add these panels to your Grafana dashboard:

#### 1. Volatility Over Time
```sql
SELECT 
  bucket AS "time",
  hl_range_pct * 100 AS "BTC Volatility %"
FROM features_1m 
WHERE symbol = 'BTC/USDT'
  AND $__timeFilter(bucket)
ORDER BY bucket
```

#### 2. VWAP Gap Distribution
```sql
SELECT 
  bucket AS "time",
  vwap_gap AS "BTC VWAP Gap",
  0 AS "Zero Line"
FROM features_1m 
WHERE symbol = 'BTC/USDT'
  AND $__timeFilter(bucket)
ORDER BY bucket
```

#### 3. Feature Statistics (Stat Panel)
```sql
SELECT 
  COUNT(*) AS "Records (1h)",
  AVG(hl_range_pct) * 100 AS "Avg Volatility %",
  SUM(is_green) AS "Green Candles",
  MAX(parkinson_vol) AS "Max Parkinson Vol"
FROM features_1m 
WHERE symbol = 'BTC/USDT'
  AND bucket >= NOW() - INTERVAL '1 hour'
```

## 🔍 Data Quality Monitoring

### Feature Validation Script
```python
def validate_features():
    """Validate feature data quality"""
    
    # Check data freshness
    sql_freshness = """
    SELECT symbol, 
           MAX(bucket) as latest,
           EXTRACT(EPOCH FROM (NOW() - MAX(bucket)))/60 as minutes_behind
    FROM features_1m 
    GROUP BY symbol
    """
    freshness = pd.read_sql(sql_freshness, engine)
    
    # Check for null values
    sql_nulls = """
    SELECT symbol,
           COUNT(*) as total_records,
           COUNT(parkinson_vol) as parkinson_records,
           COUNT(vwap_gap) as vwap_records
    FROM features_1m 
    WHERE bucket >= NOW() - INTERVAL '24 hours'
    GROUP BY symbol
    """
    nulls = pd.read_sql(sql_nulls, engine)
    
    # Check feature ranges
    sql_ranges = """
    SELECT symbol,
           MIN(hl_range_pct) as min_volatility,
           MAX(hl_range_pct) as max_volatility,
           AVG(hl_range_pct) as avg_volatility
    FROM features_1m 
    WHERE bucket >= NOW() - INTERVAL '24 hours'
    GROUP BY symbol
    """
    ranges = pd.read_sql(sql_ranges, engine)
    
    return {
        'freshness': freshness,
        'null_check': nulls,
        'ranges': ranges
    }

# Run validation
validation = validate_features()
print("Data freshness:")
print(validation['freshness'])
```

## 🎯 Best Practices

### Performance Tips
1. **Use time ranges**: Always filter by `bucket` for better query performance
2. **Symbol filtering**: Filter by symbol early in your queries
3. **Batch processing**: Load larger time ranges in batches for feature engineering
4. **Index usage**: The system is optimized for time-series queries

### Feature Engineering Tips
1. **Combine timeframes**: Use the 1-minute features with 5-minute and 1-hour aggregates
2. **Rolling features**: Build rolling statistics on top of the base features
3. **Cross-symbol**: Compare BTC and ETH features for market regime detection
4. **Lagged features**: Use time shifts for predictive models

### Production Considerations
1. **Connection pooling**: Use connection pools for high-frequency applications
2. **Caching**: Cache frequently accessed feature calculations
3. **Monitoring**: Monitor feature refresh jobs and data quality
4. **Backup**: The continuous aggregates are backed up with your main database

## 🚀 Next Steps

Your feature engineering system is now **production-ready**! You can:

1. **Build ML models** using the comprehensive feature set
2. **Create trading algorithms** with real-time feature access
3. **Develop backtesting frameworks** with historical features
4. **Monitor market regimes** using volatility and momentum features

The features auto-refresh every minute, so your models always have fresh data! 🎯