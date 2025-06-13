#!/usr/bin/env python3
"""
CoinGecko Historical Data Backfill for AlphaDB
Fetches 90 days of OHLCV data for BTC and ETH from CoinGecko Pro API
"""
import requests
import psycopg2
import datetime as dt
import os
import time
import logging
from typing import List, Tuple, Dict, Any
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinGeckoBackfill:
    def __init__(self):
        self.api_key = os.getenv("COINGECKO_API_KEY")
        if not self.api_key:
            raise ValueError("COINGECKO_API_KEY environment variable required")
        
        self.base_url = "https://pro-api.coingecko.com/api/v3"
        self.session = requests.Session()
        self.session.headers.update({
            'X-Cg-Pro-Api-Key': self.api_key,
            'Content-Type': 'application/json'
        })
        
        # CoinGecko coin IDs for our symbols
        self.coin_mapping = {
            'BTC/USDT': {'id': 'bitcoin', 'table': 'ohlcv_btc_usdt'},
            'ETH/USDT': {'id': 'ethereum', 'table': 'ohlcv_eth_usdt'}
        }
    
    def connect_db(self):
        """Connect to TimescaleDB"""
        return psycopg2.connect(
            dbname=os.getenv("POSTGRES_DB", "market"),
            user=os.getenv("POSTGRES_USER", "trader"),
            password=os.getenv("POSTGRES_PASSWORD", "s3cr3t"),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432"))
        )
    
    def fetch_minute_data(self, coin_id: str, days: int = 90) -> List[List]:
        """
        Fetch 1-minute OHLCV data from CoinGecko Pro API
        Uses market_chart/range endpoint with 1-minute granularity
        Returns list of [timestamp, open, high, low, close, volume] arrays
        """
        logger.info(f"Fetching {days} days of 1-minute data for {coin_id}")
        
        # Calculate timestamp range
        end_time = dt.datetime.utcnow()
        start_time = end_time - dt.timedelta(days=days)
        
        # CoinGecko expects timestamps in seconds
        from_timestamp = int(start_time.timestamp())
        to_timestamp = int(end_time.timestamp())
        
        url = f"{self.base_url}/coins/{coin_id}/market_chart/range"
        params = {
            'vs_currency': 'usd',
            'from': from_timestamp,
            'to': to_timestamp,
            'precision': 'full'
        }
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract prices and volumes
            prices = data.get('prices', [])
            volumes = data.get('total_volumes', [])
            
            logger.info(f"Retrieved {len(prices)} price points for {coin_id}")
            
            # Convert to OHLCV format by grouping into 1-minute buckets
            ohlcv_data = self._convert_to_ohlcv(prices, volumes)
            
            logger.info(f"Converted to {len(ohlcv_data)} OHLCV bars for {coin_id}")
            return ohlcv_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching data for {coin_id}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            raise
    
    def _convert_to_ohlcv(self, prices: List[List], volumes: List[List]) -> List[List]:
        """
        Convert price points to OHLCV 1-minute bars
        """
        if not prices:
            return []
        
        # Create volume lookup
        volume_dict = {int(v[0]): v[1] for v in volumes}
        
        # Group prices into 1-minute buckets
        ohlcv_bars = []
        current_minute = None
        minute_prices = []
        
        for timestamp_ms, price in prices:
            # Round to minute
            minute_timestamp = int(timestamp_ms // 60000) * 60000
            
            if current_minute is None:
                current_minute = minute_timestamp
                minute_prices = [price]
            elif minute_timestamp == current_minute:
                minute_prices.append(price)
            else:
                # Create OHLCV bar for previous minute
                if minute_prices:
                    volume = volume_dict.get(current_minute, 0.0)
                    ohlcv_bar = [
                        current_minute,
                        minute_prices[0],   # open
                        max(minute_prices), # high
                        min(minute_prices), # low
                        minute_prices[-1],  # close
                        volume
                    ]
                    ohlcv_bars.append(ohlcv_bar)
                
                # Start new minute
                current_minute = minute_timestamp
                minute_prices = [price]
        
        # Don't forget the last minute
        if minute_prices and current_minute:
            volume = volume_dict.get(current_minute, 0.0)
            ohlcv_bar = [
                current_minute,
                minute_prices[0],   # open
                max(minute_prices), # high
                min(minute_prices), # low
                minute_prices[-1],  # close
                volume
            ]
            ohlcv_bars.append(ohlcv_bar)
        
        return ohlcv_bars
    
    
    def process_and_insert_data(self, cursor, symbol: str, ohlcv_data: List[List]) -> int:
        """
        Process OHLCV data and insert into database
        Returns number of rows inserted
        """
        coin_info = self.coin_mapping[symbol]
        table_name = coin_info['table']
        
        logger.info(f"Processing {len(ohlcv_data)} OHLCV bars for {symbol}")
        
        inserted_count = 0
        skipped_count = 0
        
        for ohlcv_bar in ohlcv_data:
            if len(ohlcv_bar) < 6:
                logger.warning(f"Invalid OHLCV bar format: {ohlcv_bar}")
                continue
            
            timestamp_ms, open_price, high_price, low_price, close_price, volume = ohlcv_bar
            
            # Convert timestamp to datetime
            timestamp = dt.datetime.fromtimestamp(timestamp_ms / 1000.0)
            
            try:
                cursor.execute(f"""
                    INSERT INTO {table_name} (ts, open, high, low, close, vol)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ts) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        vol = EXCLUDED.vol
                """, (timestamp, open_price, high_price, low_price, close_price, volume))
                
                if cursor.rowcount > 0:
                    inserted_count += 1
                else:
                    skipped_count += 1
                
            except Exception as e:
                logger.error(f"Error inserting bar {timestamp}: {e}")
                continue
        
        logger.info(f"Inserted: {inserted_count}, Updated/Skipped: {skipped_count}")
        return inserted_count
    
    def verify_data_integrity(self, cursor, symbol: str, expected_days: int):
        """Verify the integrity of backfilled data"""
        coin_info = self.coin_mapping[symbol]
        table_name = coin_info['table']
        
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
        result = cursor.fetchone()
        if result and result[0]:
            earliest, latest, days_span = result
        else:
            earliest = latest = days_span = None
        
        # Check for gaps (periods with no data) - allowing for daily data
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
        - Days span: {days_span:.1f} days
        - Data gaps (>5 min): {gap_count}
        - Expected ~{expected_days * 1440:,} bars for {expected_days} days (1-minute data)
        """)
        
        return {
            'total_count': total_count,
            'earliest': earliest,
            'latest': latest,
            'days_span': days_span,
            'gap_count': gap_count
        }
    
    def backfill_symbol(self, symbol: str, days: int = 90):
        """Backfill data for a single symbol"""
        logger.info(f"Starting backfill for {symbol}")
        
        coin_info = self.coin_mapping[symbol]
        coin_id = coin_info['id']
        
        # Fetch 1-minute OHLCV data
        ohlcv_data = self.fetch_minute_data(coin_id, days)
        
        # Connect to database
        pg = self.connect_db()
        cursor = pg.cursor()
        
        try:
            # Insert data
            inserted_count = self.process_and_insert_data(cursor, symbol, ohlcv_data)
            pg.commit()
            
            logger.info(f"Successfully inserted {inserted_count} bars for {symbol}")
            
            # Verify data integrity
            self.verify_data_integrity(cursor, symbol, days)
            
            return inserted_count
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            pg.rollback()
            raise
        finally:
            cursor.close()
            pg.close()
    
    def run_backfill(self, days: int = 90):
        """Run complete backfill process"""
        symbols = list(self.coin_mapping.keys())
        logger.info(f"Starting CoinGecko backfill for {symbols}")
        logger.info(f"Fetching {days} days of data")
        
        results = {}
        
        for symbol in symbols:
            try:
                logger.info(f"\n{'='*50}")
                logger.info(f"Processing {symbol}")
                logger.info(f"{'='*50}")
                
                inserted_count = self.backfill_symbol(symbol, days)
                results[symbol] = inserted_count
                
                # Rate limiting - be respectful to CoinGecko API
                logger.info("Waiting 3 seconds before next symbol...")
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"Failed to backfill {symbol}: {e}")
                results[symbol] = 0
                continue
        
        # Final summary
        logger.info(f"\n{'='*50}")
        logger.info("CoinGecko Backfill Summary")
        logger.info(f"{'='*50}")
        
        total_inserted = 0
        for symbol, count in results.items():
            logger.info(f"{symbol}: {count:,} bars inserted")
            total_inserted += count
        
        logger.info(f"Total: {total_inserted:,} bars inserted across all symbols")
        logger.info("CoinGecko backfill completed successfully!")

def main():
    """Main backfill process"""
    try:
        backfiller = CoinGeckoBackfill()
        backfiller.run_backfill(days=90)
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        return 1
    return 0

if __name__ == "__main__":
    exit(main())