#!/usr/bin/env python3
"""
Simple AlphaDB Features Export for Small Datasets

For testing/demo purposes with limited historical data.
Creates a basic feature set without extensive rolling windows.
"""

import pandas as pd
from sqlalchemy import create_engine
import os
from pathlib import Path

def export_simple_features(output_dir="data/features", hours=24):
    """Export simple features suitable for small datasets"""
    
    # Database connection
    db_url = os.getenv("DATABASE_URL", "postgresql://trader:s3cr3t@localhost:5432/market")
    engine = create_engine(db_url)
    
    # Create output directory
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Simple query with basic features
    sql = f"""
    SELECT 
        bucket,
        symbol,
        close_price,
        hl_range_pct,
        vwap_gap,
        parkinson_vol,
        volume,
        is_green::int as is_green,
        price_position
    FROM features_1m 
    WHERE bucket >= NOW() - INTERVAL '{hours} hours'
    ORDER BY symbol, bucket
    """
    
    df = pd.read_sql(sql, engine)
    print(f"Loaded {len(df):,} records")
    
    if len(df) == 0:
        print("No data found!")
        return None
    
    # Add simple derived features
    df = df.sort_values(['symbol', 'bucket'])
    
    # Add basic lags (only short ones)
    for lag in [1, 5]:
        df[f'close_lag_{lag}'] = df.groupby('symbol')['close_price'].shift(lag)
        df[f'return_{lag}m'] = df.groupby('symbol')['close_price'].pct_change(lag)
    
    # Add simple rolling features (short windows only)
    for window in [5, 10]:
        df[f'vol_ma_{window}'] = df.groupby('symbol')['hl_range_pct'].rolling(window).mean().values
        df[f'close_ma_{window}'] = df.groupby('symbol')['close_price'].rolling(window).mean().values
    
    # Add simple targets
    df['target_1m'] = df.groupby('symbol')['close_price'].pct_change(1).shift(-1)
    df['target_5m'] = df.groupby('symbol')['close_price'].pct_change(5).shift(-5)
    
    # Keep rows with minimal missing data
    df_clean = df.dropna(subset=['close_lag_1', 'vol_ma_5'])  # Only drop if basic features missing
    
    print(f"After cleaning: {len(df_clean):,} records")
    print(f"Columns: {list(df_clean.columns)}")
    
    # Save
    filename = f"simple_features_{hours}h.parquet"
    filepath = output_dir / filename
    
    df_clean.to_parquet(filepath, engine='pyarrow', compression='snappy', index=False)
    
    print(f"Saved to: {filepath}")
    return filepath

if __name__ == "__main__":
    export_simple_features(hours=24)