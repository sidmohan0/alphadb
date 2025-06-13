#!/usr/bin/env python3
"""
AlphaDB Features Export Script

Exports engineered features from TimescaleDB to Parquet files for ML/backtesting.
Supports both historical backfills and incremental exports.

Usage:
    python export_features.py --backfill --days 90        # Export last 90 days
    python export_features.py --incremental --hours 24    # Export last 24 hours
    python export_features.py --symbols BTC/USDT ETH/USDT # Specific symbols
"""

import os
import argparse
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import create_engine
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FeaturesExporter:
    def __init__(self, db_url=None, output_dir="data/features"):
        """Initialize the features exporter
        
        Args:
            db_url: Database connection string
            output_dir: Directory to save parquet files
        """
        self.db_url = db_url or os.getenv(
            "DATABASE_URL", 
            "postgresql://trader:s3cr3t@localhost:5432/market"
        )
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.engine = create_engine(self.db_url)
        logger.info(f"Connected to database: {self.db_url}")
        logger.info(f"Output directory: {self.output_dir}")

    def get_available_symbols(self):
        """Get all available symbols in features table"""
        sql = "SELECT DISTINCT symbol FROM features_1m ORDER BY symbol"
        symbols = pd.read_sql(sql, self.engine)['symbol'].tolist()
        logger.info(f"Available symbols: {symbols}")
        return symbols

    def get_date_range(self):
        """Get available date range in features table"""
        sql = """
        SELECT 
            MIN(bucket) as earliest_date,
            MAX(bucket) as latest_date,
            COUNT(*) as total_records
        FROM features_1m
        """
        result = pd.read_sql(sql, self.engine).iloc[0]
        logger.info(f"Data range: {result['earliest_date']} to {result['latest_date']}")
        logger.info(f"Total records: {result['total_records']:,}")
        return result

    def export_features(self, symbols=None, start_date=None, end_date=None, 
                       chunk_size=100000):
        """Export features to parquet files
        
        Args:
            symbols: List of symbols to export (default: all)
            start_date: Start date for export 
            end_date: End date for export
            chunk_size: Number of records per chunk for memory efficiency
        """
        
        if symbols is None:
            symbols = self.get_available_symbols()
        
        # Build SQL query
        sql = """
        SELECT 
            bucket,
            symbol,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            hl_range,
            hl_range_pct,
            body_size,
            body_pct,
            vwap_gap,
            parkinson_vol,
            price_position,
            is_green,
            is_doji
        FROM features_1m 
        WHERE 1=1
        """
        
        params = []
        
        if symbols:
            placeholders = ','.join([f"'{symbol}'" for symbol in symbols])
            sql += f" AND symbol IN ({placeholders})"
            
        if start_date:
            sql += f" AND bucket >= '{start_date}'"
            
        if end_date:
            sql += f" AND bucket <= '{end_date}'"
            
        sql += " ORDER BY symbol, bucket"
        
        logger.info(f"Exporting features for symbols: {symbols}")
        logger.info(f"Date range: {start_date} to {end_date}")
        
        # Export in chunks for memory efficiency  
        chunk_iter = pd.read_sql(sql, self.engine, chunksize=chunk_size)
        
        all_chunks = []
        total_records = 0
        
        for i, chunk in enumerate(chunk_iter):
            logger.info(f"Processing chunk {i+1}, records: {len(chunk):,}")
            all_chunks.append(chunk)
            total_records += len(chunk)
            
        # Combine all chunks
        if all_chunks:
            df = pd.concat(all_chunks, ignore_index=True)
            logger.info(f"Total records exported: {total_records:,}")
            
            # Generate filename
            start_str = start_date.strftime('%Y%m%d') if start_date else 'all'
            end_str = end_date.strftime('%Y%m%d') if end_date else 'all'
            symbols_str = '-'.join(s.replace('/', '') for s in symbols)
            
            filename = f"features_{symbols_str}_{start_str}_to_{end_str}.parquet"
            filepath = self.output_dir / filename
            
            # Save to parquet with optimal settings
            df.to_parquet(
                filepath,
                engine='pyarrow',
                compression='snappy',
                index=False
            )
            
            logger.info(f"Saved {total_records:,} records to: {filepath}")
            logger.info(f"File size: {filepath.stat().st_size / 1024 / 1024:.1f} MB")
            
            # Generate metadata
            self._save_metadata(df, filepath)
            
            return filepath
        else:
            logger.warning("No data found for the specified criteria")
            return None

    def export_by_symbol(self, symbols=None, start_date=None, end_date=None):
        """Export features with separate files per symbol"""
        
        if symbols is None:
            symbols = self.get_available_symbols()
            
        filepaths = []
        
        for symbol in symbols:
            logger.info(f"Exporting {symbol}...")
            filepath = self.export_features(
                symbols=[symbol], 
                start_date=start_date, 
                end_date=end_date
            )
            if filepath:
                filepaths.append(filepath)
                
        return filepaths

    def export_ml_ready_features(self, symbols=None, days=30, target_periods=[1, 5, 15]):
        """Export ML-ready features with targets and additional derived features
        
        Args:
            symbols: Symbols to export
            days: Number of days to look back
            target_periods: Future periods for target creation (in minutes)
        """
        
        if symbols is None:
            symbols = self.get_available_symbols()
            
        start_date = datetime.now() - timedelta(days=days)
        
        # Get base features
        symbols_str = "', '".join(symbols)
        sql = f"""
        SELECT 
            bucket,
            symbol,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            hl_range_pct,
            vwap_gap,
            parkinson_vol,
            price_position,
            is_green::int as is_green,
            is_doji::int as is_doji
        FROM features_1m 
        WHERE symbol IN ('{symbols_str}')
          AND bucket >= '{start_date}'
        ORDER BY symbol, bucket
        """
        
        df = pd.read_sql(sql, self.engine)
        logger.info(f"Loaded {len(df):,} base feature records")
        
        # Add derived features for ML
        df = self._add_ml_features(df, target_periods)
        
        # Save ML-ready dataset
        filename = f"ml_features_{'-'.join(s.replace('/', '') for s in symbols)}_{days}d.parquet"
        filepath = self.output_dir / filename
        
        df.to_parquet(filepath, engine='pyarrow', compression='snappy', index=False)
        
        logger.info(f"Saved ML-ready features: {filepath}")
        logger.info(f"Features shape: {df.shape}")
        logger.info(f"Columns: {list(df.columns)}")
        
        return filepath

    def _add_ml_features(self, df, target_periods):
        """Add ML-specific features like lags, rolling stats, and targets"""
        
        df = df.copy()
        df = df.sort_values(['symbol', 'bucket'])
        
        logger.info("Adding ML features...")
        
        # Add time-based features
        df['hour'] = pd.to_datetime(df['bucket']).dt.hour
        df['day_of_week'] = pd.to_datetime(df['bucket']).dt.dayofweek
        
        # Add lagged features
        lag_periods = [1, 5, 15, 60]  # 1min, 5min, 15min, 1hour
        for lag in lag_periods:
            df[f'close_lag_{lag}'] = df.groupby('symbol')['close_price'].shift(lag)
            df[f'vol_lag_{lag}'] = df.groupby('symbol')['hl_range_pct'].shift(lag)
            df[f'vwap_gap_lag_{lag}'] = df.groupby('symbol')['vwap_gap'].shift(lag)
        
        # Add rolling features
        windows = [5, 15, 60, 240]  # 5min, 15min, 1hour, 4hour
        for window in windows:
            # Rolling volatility
            df[f'vol_ma_{window}'] = df.groupby('symbol')['hl_range_pct'].rolling(window).mean().values
            df[f'vol_std_{window}'] = df.groupby('symbol')['hl_range_pct'].rolling(window).std().values
            
            # Rolling VWAP gap
            df[f'vwap_gap_ma_{window}'] = df.groupby('symbol')['vwap_gap'].rolling(window).mean().values
            
            # Rolling price features
            df[f'close_ma_{window}'] = df.groupby('symbol')['close_price'].rolling(window).mean().values
            df[f'volume_ma_{window}'] = df.groupby('symbol')['volume'].rolling(window).mean().values
            
        # Add price momentum features
        for period in [5, 15, 60]:
            df[f'return_{period}m'] = df.groupby('symbol')['close_price'].pct_change(period)
            df[f'return_{period}m_abs'] = df[f'return_{period}m'].abs()
            
        # Add volatility regime indicators (only if we have enough data)
        try:
            df['vol_regime'] = df.groupby('symbol')['hl_range_pct'].apply(
                lambda x: pd.qcut(x.rolling(min(60, len(x)//4)).mean(), q=3, labels=['low', 'medium', 'high'], duplicates='drop')
            ).values
        except ValueError:
            # Not enough data for regime classification
            df['vol_regime'] = 'medium'
        
        # Add target variables (future returns)
        for period in target_periods:
            df[f'target_{period}m'] = df.groupby('symbol')['close_price'].pct_change(period).shift(-period)
            df[f'target_{period}m_sign'] = (df[f'target_{period}m'] > 0).astype(int)
            
        # Drop rows with insufficient history or future data
        df = df.dropna()
        
        logger.info(f"Added {len([c for c in df.columns if c.endswith(('_lag_', '_ma_', '_std_', 'target_'))])} derived features")
        
        return df

    def _save_metadata(self, df, filepath):
        """Save metadata about the exported dataset"""
        
        metadata = {
            'export_timestamp': datetime.now().isoformat(),
            'total_records': len(df),
            'symbols': df['symbol'].unique().tolist(),
            'date_range': {
                'start': df['bucket'].min().isoformat(),
                'end': df['bucket'].max().isoformat()
            },
            'columns': list(df.columns),
            'dtypes': df.dtypes.astype(str).to_dict(),
            'file_size_mb': filepath.stat().st_size / 1024 / 1024
        }
        
        metadata_path = filepath.with_suffix('.json')
        
        import json
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        logger.info(f"Saved metadata: {metadata_path}")

    def export_vectorbt_ready(self, symbol='BTC/USDT', days=90):
        """Export data in VectorBT-ready format with OHLCV + features"""
        
        start_date = datetime.now() - timedelta(days=days)
        
        sql = f"""
        SELECT 
            bucket as timestamp,
            open_price as open,
            high_price as high,
            low_price as low,
            close_price as close,
            volume,
            hl_range_pct,
            vwap_gap,
            parkinson_vol,
            is_green::int as is_green
        FROM features_1m 
        WHERE symbol = '{symbol}'
          AND bucket >= '{start_date}'
        ORDER BY bucket
        """
        
        df = pd.read_sql(sql, self.engine)
        df.set_index('timestamp', inplace=True)
        
        # Save VectorBT-ready format
        symbol_clean = symbol.replace('/', '')
        filename = f"vectorbt_{symbol_clean}_{days}d.parquet"
        filepath = self.output_dir / filename
        
        df.to_parquet(filepath, engine='pyarrow', compression='snappy')
        
        logger.info(f"Saved VectorBT-ready data: {filepath}")
        logger.info(f"Shape: {df.shape}, Index: {df.index.name}")
        
        return filepath


def main():
    parser = argparse.ArgumentParser(description='Export AlphaDB features to Parquet')
    
    parser.add_argument('--backfill', action='store_true', 
                       help='Export historical data')
    parser.add_argument('--incremental', action='store_true',
                       help='Export recent data only')
    parser.add_argument('--ml-ready', action='store_true',
                       help='Export ML-ready features with targets')
    parser.add_argument('--vectorbt', action='store_true',
                       help='Export VectorBT-ready format')
    
    parser.add_argument('--symbols', nargs='+', 
                       default=['BTC/USDT', 'ETH/USDT'],
                       help='Symbols to export')
    parser.add_argument('--days', type=int, default=90,
                       help='Number of days to export')
    parser.add_argument('--hours', type=int, default=24,
                       help='Number of hours for incremental export')
    
    parser.add_argument('--output-dir', default='data/features',
                       help='Output directory for parquet files')
    parser.add_argument('--db-url', 
                       help='Database connection URL')
    
    args = parser.parse_args()
    
    exporter = FeaturesExporter(
        db_url=args.db_url,
        output_dir=args.output_dir
    )
    
    # Show available data
    exporter.get_date_range()
    
    if args.backfill:
        logger.info(f"Running backfill export for {args.days} days...")
        start_date = datetime.now() - timedelta(days=args.days)
        filepath = exporter.export_features(
            symbols=args.symbols,
            start_date=start_date
        )
        
    elif args.incremental:
        logger.info(f"Running incremental export for {args.hours} hours...")
        start_date = datetime.now() - timedelta(hours=args.hours)
        filepath = exporter.export_features(
            symbols=args.symbols,
            start_date=start_date
        )
        
    elif args.ml_ready:
        logger.info(f"Exporting ML-ready features for {args.days} days...")
        filepath = exporter.export_ml_ready_features(
            symbols=args.symbols,
            days=args.days
        )
        
    elif args.vectorbt:
        logger.info(f"Exporting VectorBT-ready data...")
        for symbol in args.symbols:
            filepath = exporter.export_vectorbt_ready(
                symbol=symbol,
                days=args.days
            )
            
    else:
        logger.info("No export type specified. Use --backfill, --incremental, --ml-ready, or --vectorbt")
        return
        
    logger.info("Export completed successfully! 🎯")


if __name__ == "__main__":
    main()