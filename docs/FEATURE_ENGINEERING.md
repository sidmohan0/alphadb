# Feature Engineering Guide for AlphaDB 🧠

A comprehensive reference for building feature engineering notebooks that connect to your TimescaleDB cryptocurrency data infrastructure.

## 📚 Table of Contents

1. [Database Connection Setup](#database-connection-setup)
2. [Data Source Overview](#data-source-overview)
3. [Basic Data Access Patterns](#basic-data-access-patterns)
4. [Technical Indicators](#technical-indicators)
5. [Time-Series Features](#time-series-features)
6. [Market Microstructure Features](#market-microstructure-features)
7. [Multi-Timeframe Analysis](#multi-timeframe-analysis)
8. [Performance Optimization](#performance-optimization)
9. [Example Notebook Structure](#example-notebook-structure)
10. [Common Patterns & Recipes](#common-patterns--recipes)

---

## Database Connection Setup

### Environment Setup
```python
import pandas as pd
import numpy as np
import psycopg2
from sqlalchemy import create_engine
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Database connection
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'market',
    'user': 'trader',
    'password': 's3cr3t'  # Use your actual password
}

# Create SQLAlchemy engine
engine = create_engine(f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")

# Test connection
def test_connection():
    try:
        with engine.connect() as conn:
            result = conn.execute("SELECT COUNT(*) FROM ohlcv_btc_usdt")
            print(f"✅ Connected! BTC records: {result.fetchone()[0]:,}")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

test_connection()
```

### Helper Functions
```python
def query_db(sql, params=None):
    """Execute SQL query and return DataFrame"""
    return pd.read_sql(sql, engine, params=params)

def get_latest_data(symbol='btc_usdt', limit=1000):
    """Get latest OHLCV data for a symbol"""
    table_name = f"ohlcv_{symbol}"
    sql = f"""
    SELECT ts, open, high, low, close, vol 
    FROM {table_name} 
    ORDER BY ts DESC 
    LIMIT %s
    """
    return query_db(sql, params=[limit])

def get_trades(symbol='XBT/USDT', hours=24):
    """Get recent trade data"""
    sql = """
    SELECT ts_exchange, price, qty, side
    FROM trades 
    WHERE symbol = %s 
      AND ts_exchange >= NOW() - INTERVAL %s
    ORDER BY ts_exchange DESC
    """
    return query_db(sql, params=[symbol, f'{hours} hours'])
```

---

## Data Source Overview

### Available Tables

| Table | Description | Granularity | Use Case |
|-------|-------------|-------------|----------|
| `ohlcv_btc_usdt` | Bitcoin historical + live OHLCV | 1-minute | Price analysis, indicators |
| `ohlcv_eth_usdt` | Ethereum historical + live OHLCV | 1-minute | Price analysis, indicators |
| `ohlcv_btc_usdt_5m` | Bitcoin 5-minute aggregates | 5-minute | Smoothed analysis |
| `ohlcv_eth_usdt_5m` | Ethereum 5-minute aggregates | 5-minute | Smoothed analysis |
| `trades` | Real-time tick data | Tick-level | Microstructure, order flow |

### Data Quality Check
```python
def data_quality_report():
    """Generate comprehensive data quality report"""
    
    tables = ['ohlcv_btc_usdt', 'ohlcv_eth_usdt', 'trades']
    
    for table in tables:
        print(f"\n📊 {table.upper()} Quality Report")
        print("=" * 50)
        
        if table == 'trades':
            sql = f"""
            SELECT 
                COUNT(*) as total_records,
                COUNT(DISTINCT symbol) as symbols,
                MIN(ts_exchange) as earliest,
                MAX(ts_exchange) as latest,
                EXTRACT(DAYS FROM (MAX(ts_exchange) - MIN(ts_exchange))) as days_span
            FROM {table}
            """
        else:
            sql = f"""
            SELECT 
                COUNT(*) as total_records,
                MIN(ts) as earliest,
                MAX(ts) as latest,
                EXTRACT(DAYS FROM (MAX(ts) - MIN(ts))) as days_span,
                COUNT(CASE WHEN vol > 0 THEN 1 END) as records_with_volume
            FROM {table}
            """
        
        df = query_db(sql)
        for col in df.columns:
            print(f"{col}: {df[col].iloc[0]}")

data_quality_report()
```

---

## Basic Data Access Patterns

### 1. Time Range Queries
```python
def get_data_range(symbol='btc_usdt', start_date='2025-03-01', end_date='2025-06-13'):
    """Get OHLCV data for specific date range"""
    sql = f"""
    SELECT ts, open, high, low, close, vol
    FROM ohlcv_{symbol}
    WHERE ts BETWEEN %s AND %s
    ORDER BY ts
    """
    return query_db(sql, params=[start_date, end_date])

# Example usage
btc_data = get_data_range('btc_usdt', '2025-05-01', '2025-06-13')
print(f"Retrieved {len(btc_data)} BTC records")
```

### 2. Recent Data Windows
```python
def get_recent_window(symbol='btc_usdt', hours=24):
    """Get data from last N hours"""
    sql = f"""
    SELECT ts, open, high, low, close, vol
    FROM ohlcv_{symbol}
    WHERE ts >= NOW() - INTERVAL %s
    ORDER BY ts
    """
    return query_db(sql, params=[f'{hours} hours'])

# Get last 24 hours of BTC data
recent_btc = get_recent_window('btc_usdt', 24)
```

### 3. Aggregated Views
```python
def get_hourly_aggregates(symbol='btc_usdt', days=7):
    """Create hourly OHLCV from minute data"""
    sql = f"""
    SELECT 
        time_bucket('1 hour', ts) AS hour_bucket,
        first(open, ts) AS open,
        max(high) AS high,
        min(low) AS low,
        last(close, ts) AS close,
        sum(vol) AS volume
    FROM ohlcv_{symbol}
    WHERE ts >= NOW() - INTERVAL %s
    GROUP BY hour_bucket
    ORDER BY hour_bucket
    """
    return query_db(sql, params=[f'{days} days'])

hourly_btc = get_hourly_aggregates('btc_usdt', 30)
```

---

## Technical Indicators

### Moving Averages
```python
def add_moving_averages(df, price_col='close'):
    """Add various moving averages"""
    df = df.copy()
    
    # Simple Moving Averages
    for period in [5, 10, 20, 50, 100, 200]:
        df[f'sma_{period}'] = df[price_col].rolling(window=period).mean()
    
    # Exponential Moving Averages
    for period in [12, 26, 50, 200]:
        df[f'ema_{period}'] = df[price_col].ewm(span=period).mean()
    
    return df

def add_macd(df, price_col='close'):
    """Add MACD indicator"""
    df = df.copy()
    
    # MACD components
    ema_12 = df[price_col].ewm(span=12).mean()
    ema_26 = df[price_col].ewm(span=26).mean()
    
    df['macd'] = ema_12 - ema_26
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_histogram'] = df['macd'] - df['macd_signal']
    
    return df
```

### Bollinger Bands
```python
def add_bollinger_bands(df, price_col='close', period=20, std_dev=2):
    """Add Bollinger Bands"""
    df = df.copy()
    
    sma = df[price_col].rolling(window=period).mean()
    std = df[price_col].rolling(window=period).std()
    
    df['bb_upper'] = sma + (std * std_dev)
    df['bb_middle'] = sma
    df['bb_lower'] = sma - (std * std_dev)
    df['bb_width'] = df['bb_upper'] - df['bb_lower']
    df['bb_position'] = (df[price_col] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    return df
```

### RSI (Relative Strength Index)
```python
def add_rsi(df, price_col='close', period=14):
    """Add RSI indicator"""
    df = df.copy()
    
    delta = df[price_col].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df
```

### Volume Indicators
```python
def add_volume_indicators(df):
    """Add volume-based indicators"""
    df = df.copy()
    
    # Volume moving averages
    df['vol_sma_20'] = df['vol'].rolling(window=20).mean()
    df['vol_ratio'] = df['vol'] / df['vol_sma_20']
    
    # On-Balance Volume
    df['obv'] = (np.sign(df['close'].diff()) * df['vol']).fillna(0).cumsum()
    
    # Volume Weighted Average Price (VWAP)
    df['vwap'] = (df['close'] * df['vol']).cumsum() / df['vol'].cumsum()
    
    return df
```

---

## Time-Series Features

### Price Action Features
```python
def add_price_features(df):
    """Add price action features"""
    df = df.copy()
    
    # Price changes
    df['price_change'] = df['close'].diff()
    df['price_change_pct'] = df['close'].pct_change()
    
    # High-Low range
    df['hl_range'] = df['high'] - df['low']
    df['hl_range_pct'] = df['hl_range'] / df['close']
    
    # Open-Close relationship
    df['body_size'] = abs(df['close'] - df['open'])
    df['body_size_pct'] = df['body_size'] / df['close']
    df['upper_shadow'] = df['high'] - np.maximum(df['open'], df['close'])
    df['lower_shadow'] = np.minimum(df['open'], df['close']) - df['low']
    
    # Candle type
    df['is_green'] = (df['close'] > df['open']).astype(int)
    df['is_doji'] = (df['body_size_pct'] < 0.001).astype(int)
    
    return df
```

### Momentum Features
```python
def add_momentum_features(df, periods=[1, 5, 10, 20]):
    """Add momentum and rate of change features"""
    df = df.copy()
    
    for period in periods:
        # Rate of Change
        df[f'roc_{period}'] = df['close'].pct_change(periods=period)
        
        # Price momentum
        df[f'momentum_{period}'] = df['close'] / df['close'].shift(period) - 1
        
        # High/Low momentum
        df[f'high_momentum_{period}'] = df['high'] / df['high'].shift(period) - 1
        df[f'low_momentum_{period}'] = df['low'] / df['low'].shift(period) - 1
    
    return df
```

### Volatility Features
```python
def add_volatility_features(df, periods=[5, 10, 20]):
    """Add volatility measures"""
    df = df.copy()
    
    # Simple volatility (rolling standard deviation)
    for period in periods:
        df[f'volatility_{period}'] = df['close'].pct_change().rolling(window=period).std()
    
    # True Range and Average True Range
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift()),
            abs(df['low'] - df['close'].shift())
        )
    )
    df['atr_14'] = df['tr'].rolling(window=14).mean()
    
    # Garman-Klass volatility estimator
    df['gk_volatility'] = np.sqrt(
        0.5 * (np.log(df['high'] / df['low'])) ** 2 - 
        (2 * np.log(2) - 1) * (np.log(df['close'] / df['open'])) ** 2
    )
    
    return df
```

---

## Market Microstructure Features

### Order Flow Analysis
```python
def get_order_flow_features(hours=24):
    """Analyze order flow from tick data"""
    
    sql = """
    SELECT 
        time_bucket('1 minute', ts_exchange) AS minute_bucket,
        symbol,
        COUNT(*) as trade_count,
        SUM(qty) as total_volume,
        SUM(CASE WHEN side = 'buy' THEN qty ELSE 0 END) as buy_volume,
        SUM(CASE WHEN side = 'sell' THEN qty ELSE 0 END) as sell_volume,
        AVG(price) as avg_price,
        STDDEV(price) as price_std,
        MAX(price) - MIN(price) as price_range
    FROM trades 
    WHERE ts_exchange >= NOW() - INTERVAL %s
    GROUP BY minute_bucket, symbol
    ORDER BY minute_bucket, symbol
    """
    
    df = query_db(sql, params=[f'{hours} hours'])
    
    # Calculate order flow features
    df['buy_sell_ratio'] = df['buy_volume'] / df['sell_volume']
    df['net_volume'] = df['buy_volume'] - df['sell_volume']
    df['volume_imbalance'] = df['net_volume'] / df['total_volume']
    
    return df

def add_microstructure_features(df_ohlcv, df_trades):
    """Merge OHLCV with microstructure features"""
    
    # Align timestamps (assuming minute_bucket maps to ts)
    df_trades_agg = df_trades.groupby('minute_bucket').agg({
        'trade_count': 'sum',
        'total_volume': 'sum',
        'buy_sell_ratio': 'mean',
        'volume_imbalance': 'mean'
    }).reset_index()
    
    # Merge with OHLCV data
    df_merged = pd.merge_asof(
        df_ohlcv.sort_values('ts'),
        df_trades_agg.sort_values('minute_bucket'),
        left_on='ts',
        right_on='minute_bucket',
        direction='nearest'
    )
    
    return df_merged
```

### Price Impact Features
```python
def add_price_impact_features(df):
    """Add features related to price impact and liquidity"""
    df = df.copy()
    
    # Price impact of volume
    df['vol_price_impact'] = df['hl_range'] / np.log1p(df['vol'])
    
    # Efficiency ratio (trending vs. ranging)
    periods = [10, 20, 50]
    for period in periods:
        price_move = abs(df['close'] - df['close'].shift(period))
        volatility_sum = df['hl_range'].rolling(window=period).sum()
        df[f'efficiency_ratio_{period}'] = price_move / volatility_sum
    
    return df
```

---

## Multi-Timeframe Analysis

### Cross-Timeframe Features
```python
def create_multi_timeframe_features(symbol='btc_usdt'):
    """Create features across multiple timeframes"""
    
    # Get base 1-minute data
    df_1m = get_recent_window(symbol, hours=168)  # 1 week
    
    # Create different timeframe aggregations
    timeframes = {
        '5T': 5,   # 5 minutes
        '15T': 15, # 15 minutes
        '1H': 60,  # 1 hour
        '4H': 240, # 4 hours
        '1D': 1440 # 1 day
    }
    
    features_df = df_1m[['ts', 'close']].copy()
    
    for tf_name, minutes in timeframes.items():
        # Resample to timeframe
        tf_data = df_1m.set_index('ts').resample(f'{minutes}T').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'vol': 'sum'
        }).dropna()
        
        # Add indicators for this timeframe
        tf_data = add_moving_averages(tf_data.reset_index())
        tf_data = add_rsi(tf_data)
        
        # Merge back to 1-minute data
        merge_cols = [f'{tf_name}_{col}' for col in ['sma_20', 'rsi']]
        tf_data_merge = tf_data[['ts'] + ['sma_20', 'rsi']].copy()
        tf_data_merge.columns = ['ts'] + merge_cols
        
        features_df = pd.merge_asof(
            features_df,
            tf_data_merge,
            on='ts',
            direction='backward'
        )
    
    return features_df

# Example usage
multi_tf_features = create_multi_timeframe_features('btc_usdt')
```

### Regime Detection
```python
def add_market_regime_features(df, lookback_periods=[20, 50, 100]):
    """Add market regime detection features"""
    df = df.copy()
    
    for period in lookback_periods:
        # Trend strength
        df[f'trend_strength_{period}'] = (
            df['close'] - df['close'].shift(period)
        ) / df['close'].shift(period)
        
        # Volatility regime
        vol_rolling = df['close'].pct_change().rolling(window=period).std()
        vol_percentile = vol_rolling.rolling(window=period*2).rank(pct=True)
        df[f'vol_regime_{period}'] = vol_percentile
        
        # Price regime (relative to historical range)
        high_rolling = df['high'].rolling(window=period).max()
        low_rolling = df['low'].rolling(window=period).min()
        df[f'price_position_{period}'] = (
            (df['close'] - low_rolling) / (high_rolling - low_rolling)
        )
    
    return df
```

---

## Performance Optimization

### Efficient Data Loading
```python
def load_data_efficiently(symbol='btc_usdt', days=30):
    """Load data with optimized queries"""
    
    # Use connection pooling for better performance
    sql = f"""
    SELECT ts, open, high, low, close, vol
    FROM ohlcv_{symbol}
    WHERE ts >= NOW() - INTERVAL %s
    ORDER BY ts
    """
    
    # Read in chunks for large datasets
    chunk_size = 10000
    chunks = []
    
    with engine.connect() as conn:
        result = conn.execute(sql, [f'{days} days'])
        while True:
            chunk = result.fetchmany(chunk_size)
            if not chunk:
                break
            chunks.append(pd.DataFrame(chunk, columns=['ts', 'open', 'high', 'low', 'close', 'vol']))
    
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()

def cache_features(df, symbol, feature_set_name):
    """Cache computed features to avoid recomputation"""
    cache_file = f"/tmp/features_{symbol}_{feature_set_name}_{datetime.now().strftime('%Y%m%d')}.pkl"
    df.to_pickle(cache_file)
    print(f"Features cached to {cache_file}")
    return cache_file
```

### Batch Processing
```python
def process_features_batch(symbols=['btc_usdt', 'eth_usdt'], days=30):
    """Process features for multiple symbols efficiently"""
    
    all_features = {}
    
    for symbol in symbols:
        print(f"Processing {symbol}...")
        
        # Load base data
        df = load_data_efficiently(symbol, days)
        
        if len(df) == 0:
            print(f"No data for {symbol}")
            continue
        
        # Add all feature sets
        df = add_moving_averages(df)
        df = add_rsi(df)
        df = add_bollinger_bands(df)
        df = add_price_features(df)
        df = add_momentum_features(df)
        df = add_volatility_features(df)
        df = add_volume_indicators(df)
        df = add_market_regime_features(df)
        
        all_features[symbol] = df
        
        # Cache results
        cache_features(df, symbol, 'full_feature_set')
    
    return all_features
```

---

## Example Notebook Structure

### Complete Feature Engineering Pipeline
```python
def main_feature_pipeline(symbol='btc_usdt', days=30):
    """Complete feature engineering pipeline"""
    
    print(f"🚀 Starting feature engineering for {symbol}")
    
    # 1. Data Loading
    print("📊 Loading base data...")
    df = load_data_efficiently(symbol, days)
    print(f"Loaded {len(df):,} records")
    
    # 2. Data Quality Check
    print("🔍 Checking data quality...")
    missing_pct = df.isnull().sum().sum() / (len(df) * len(df.columns)) * 100
    print(f"Missing data: {missing_pct:.2f}%")
    
    # 3. Technical Indicators
    print("📈 Computing technical indicators...")
    df = add_moving_averages(df)
    df = add_macd(df)
    df = add_rsi(df)
    df = add_bollinger_bands(df)
    
    # 4. Price Action Features
    print("💰 Adding price action features...")
    df = add_price_features(df)
    df = add_momentum_features(df)
    df = add_volatility_features(df)
    
    # 5. Volume Features
    print("📊 Adding volume features...")
    df = add_volume_indicators(df)
    
    # 6. Market Regime Features
    print("🔄 Adding market regime features...")
    df = add_market_regime_features(df)
    
    # 7. Multi-timeframe Features
    print("⏰ Creating multi-timeframe features...")
    mtf_features = create_multi_timeframe_features(symbol)
    df = pd.merge(df, mtf_features, on='ts', how='left')
    
    # 8. Final cleanup
    print("🧹 Final cleanup...")
    # Remove infinite values
    df = df.replace([np.inf, -np.inf], np.nan)
    
    # Fill remaining NaN values
    numeric_columns = df.select_dtypes(include=[np.number]).columns
    df[numeric_columns] = df[numeric_columns].fillna(method='ffill')
    
    print(f"✅ Feature engineering complete! Final shape: {df.shape}")
    print(f"Features created: {len(df.columns) - 6}")  # Subtract OHLCV + timestamp
    
    return df

# Run the pipeline
features_df = main_feature_pipeline('btc_usdt', 30)
```

---

## Common Patterns & Recipes

### Quick Analysis Functions
```python
def quick_correlation_analysis(df, target='close'):
    """Quick correlation analysis of features"""
    correlations = df.corr()[target].abs().sort_values(ascending=False)
    return correlations.head(20)

def plot_feature_importance(df, target='close'):
    """Plot feature correlations with target"""
    corr = quick_correlation_analysis(df, target)
    
    fig = px.bar(
        x=corr.values[1:11],  # Skip target itself
        y=corr.index[1:11],
        orientation='h',
        title=f'Top 10 Features Correlated with {target}',
        labels={'x': 'Absolute Correlation', 'y': 'Features'}
    )
    fig.show()

def feature_summary_stats(df):
    """Generate summary statistics for all features"""
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    
    summary = pd.DataFrame({
        'count': df[numeric_cols].count(),
        'missing': df[numeric_cols].isnull().sum(),
        'missing_pct': (df[numeric_cols].isnull().sum() / len(df)) * 100,
        'mean': df[numeric_cols].mean(),
        'std': df[numeric_cols].std(),
        'min': df[numeric_cols].min(),
        'max': df[numeric_cols].max()
    })
    
    return summary.round(4)
```

### Export Functions
```python
def export_features_to_csv(df, symbol, suffix=''):
    """Export features to CSV for external analysis"""
    filename = f"features_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M')}{suffix}.csv"
    df.to_csv(filename, index=False)
    print(f"Features exported to {filename}")
    return filename

def create_feature_documentation(df):
    """Create documentation for all features"""
    feature_docs = {
        'timestamp': 'ts - Record timestamp',
        'price': 'open, high, low, close - OHLCV price data',
        'volume': 'vol - Trading volume',
        'moving_averages': 'sma_*, ema_* - Simple and exponential moving averages',
        'momentum': 'rsi, macd_* - Momentum indicators',
        'volatility': 'volatility_*, atr_*, bb_* - Volatility measures',
        'price_action': 'price_change*, hl_range*, body_size* - Price action features',
        'volume_indicators': 'vol_*, obv, vwap - Volume-based indicators',
        'regime': '*_regime_*, trend_strength* - Market regime indicators'
    }
    
    print("📚 Feature Documentation")
    print("=" * 50)
    for category, description in feature_docs.items():
        print(f"{category}: {description}")
```

---

## 🎯 Quick Start Template

Here's a complete template to get you started:

```python
# Feature Engineering Quick Start Template
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

# 1. Setup connection
engine = create_engine("postgresql://trader:s3cr3t@localhost:5432/market")

# 2. Load data
def get_data(symbol='btc_usdt', days=7):
    sql = f"""
    SELECT ts, open, high, low, close, vol
    FROM ohlcv_{symbol}
    WHERE ts >= NOW() - INTERVAL '{days} days'
    ORDER BY ts
    """
    return pd.read_sql(sql, engine)

# 3. Quick feature engineering
df = get_data('btc_usdt', 30)
df['sma_20'] = df['close'].rolling(20).mean()
df['rsi'] = # ... use functions from above
df['volatility'] = df['close'].pct_change().rolling(10).std()

# 4. Analysis
correlations = df.corr()['close'].abs().sort_values(ascending=False)
print("Top correlated features:")
print(correlations.head(10))

# 5. Export
df.to_csv('btc_features.csv', index=False)
```

---

## 📈 Next Steps

1. **Start Small**: Begin with basic indicators (SMA, RSI, Bollinger Bands)
2. **Validate Features**: Always check correlations and statistical significance
3. **Combine Timeframes**: Use both minute-level and aggregated features
4. **Monitor Performance**: Track feature computation time and database load
5. **Iterate**: Continuously add new features based on research and backtesting

Happy feature engineering! 🚀

---

*This guide serves as a living document. Update it as you discover new patterns and techniques specific to your trading strategies.*