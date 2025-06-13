#!/usr/bin/env python3
"""
Historical Data Backfill Script for AlphaDB
Fetches 90 days of OHLCV data for BTC/USDT and ETH/USDT from Kraken
"""
import ccxt
import psycopg2
import datetime as dt
import os
import time
import logging
from typing import List, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def connect_db():
    """Connect to TimescaleDB"""
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "market"),
        user=os.getenv("POSTGRES_USER", "trader"),
        password=os.getenv("POSTGRES_PASSWORD", "s3cr3t"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432"))
    )

def get_table_name(symbol: str) -> str:
    """Convert symbol to table name (e.g., BTC/USDT -> ohlcv_btc_usdt)"""
    return f"ohlcv_{symbol.replace('/', '_').replace('-', '_').lower()}"

def fetch_historical_data(exchange, symbol: str, days: int = 90) -> List[Tuple]:
    """
    Fetch historical OHLCV data from exchange
    Returns list of (timestamp, open, high, low, close, volume) tuples
    """
    logger.info(f"Fetching {days} days of historical data for {symbol}")
    
    # Calculate start time (days ago)
    end_time = dt.datetime.utcnow()
    start_time = end_time - dt.timedelta(days=days)
    since = int(start_time.timestamp() * 1000)  # Convert to milliseconds
    
    all_data = []
    current_since = since
    
    while current_since < int(end_time.timestamp() * 1000):
        try:
            # Fetch 1000 bars at a time (Kraken limit)
            logger.info(f"Fetching data from {dt.datetime.fromtimestamp(current_since/1000)}")
            bars = exchange.fetch_ohlcv(symbol, '1m', since=current_since, limit=1000)
            
            if not bars:
                logger.warning(f"No more data available for {symbol}")
                break
            
            logger.info(f"Retrieved {len(bars)} bars for {symbol}")
            all_data.extend(bars)
            
            # Update since to last timestamp + 1 minute
            last_timestamp = bars[-1][0]
            current_since = last_timestamp + 60000  # Add 1 minute in milliseconds
            
            # Rate limiting - be nice to the API
            time.sleep(1)
            
            # Break if we've caught up to current time
            if current_since >= int(end_time.timestamp() * 1000):
                break
                
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            time.sleep(5)  # Wait before retrying
            continue
    
    logger.info(f"Total bars fetched for {symbol}: {len(all_data)}")
    return all_data

def insert_historical_data(cursor, symbol: str, data: List[Tuple]) -> int:
    """
    Insert historical data into symbol-specific table
    Returns number of rows inserted
    """
    table_name = get_table_name(symbol)
    logger.info(f"Inserting {len(data)} bars into {table_name}")
    
    inserted_count = 0
    skipped_count = 0
    
    for bar in data:
        ts, o, h, l, c, v = bar
        timestamp = dt.datetime.fromtimestamp(ts / 1000.0)
        
        try:
            cursor.execute(f"""
                INSERT INTO {table_name} (ts, open, high, low, close, vol)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (ts) DO NOTHING
            """, (timestamp, o, h, l, c, v))
            
            if cursor.rowcount > 0:
                inserted_count += 1
            else:
                skipped_count += 1
                
        except Exception as e:
            logger.error(f"Error inserting bar {timestamp}: {e}")
            continue
    
    logger.info(f"Inserted: {inserted_count}, Skipped (duplicates): {skipped_count}")
    return inserted_count

def verify_data_integrity(cursor, symbol: str, expected_days: int):
    """Verify the integrity of backfilled data"""
    table_name = get_table_name(symbol)
    
    # Check total count
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    total_count = cursor.fetchone()[0]
    
    # Check date range
    cursor.execute(f"""
        SELECT 
            MIN(ts) as earliest,
            MAX(ts) as latest,
            EXTRACT(DAYS FROM (MAX(ts) - MIN(ts))) as days_span
        FROM {table_name}
    """)
    earliest, latest, days_span = cursor.fetchone()
    
    # Check for gaps (periods with no data)
    cursor.execute(f"""
        SELECT COUNT(*) as gap_count
        FROM (
            SELECT ts, LAG(ts) OVER (ORDER BY ts) as prev_ts
            FROM {table_name}
            ORDER BY ts
        ) t
        WHERE EXTRACT(EPOCH FROM (ts - prev_ts)) > 300  -- More than 5 minutes gap
    """)
    gap_count = cursor.fetchone()[0]
    
    logger.info(f"""
    Data Integrity Report for {symbol}:
    - Total bars: {total_count:,}
    - Date range: {earliest} to {latest}
    - Days span: {days_span:.1f}
    - Data gaps (>5min): {gap_count}
    - Expected ~{expected_days * 1440:,} bars for {expected_days} days
    """)
    
    return {
        'total_count': total_count,
        'earliest': earliest,
        'latest': latest,
        'days_span': days_span,
        'gap_count': gap_count
    }

def main():
    """Main backfill process"""
    symbols = ['BTC/USDT', 'ETH/USDT']
    days_to_fetch = 90
    
    logger.info(f"Starting historical backfill for {symbols}")
    logger.info(f"Fetching {days_to_fetch} days of data")
    
    # Initialize exchange
    exchange = ccxt.kraken({
        'enableRateLimit': True,
        'timeout': 30000,  # 30 second timeout
    })
    
    # Connect to database
    try:
        pg = connect_db()
        cursor = pg.cursor()
        logger.info("Connected to database successfully")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return
    
    # Process each symbol
    for symbol in symbols:
        try:
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing {symbol}")
            logger.info(f"{'='*50}")
            
            # Fetch historical data
            historical_data = fetch_historical_data(exchange, symbol, days_to_fetch)
            
            if not historical_data:
                logger.warning(f"No data fetched for {symbol}")
                continue
            
            # Insert into database
            inserted_count = insert_historical_data(cursor, symbol, historical_data)
            pg.commit()
            
            logger.info(f"Successfully inserted {inserted_count} bars for {symbol}")
            
            # Verify data integrity
            verify_data_integrity(cursor, symbol, days_to_fetch)
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            pg.rollback()
            continue
    
    # Final summary
    logger.info(f"\n{'='*50}")
    logger.info("Backfill Summary")
    logger.info(f"{'='*50}")
    
    for symbol in symbols:
        table_name = get_table_name(symbol)
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        logger.info(f"{symbol}: {count:,} bars in {table_name}")
    
    cursor.close()
    pg.close()
    logger.info("Backfill completed successfully!")

if __name__ == "__main__":
    main()