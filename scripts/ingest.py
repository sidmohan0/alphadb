"""
Dockerized crypto ingestor daemon for TimescaleDB
Supports multiple symbols via SYMBOLS environment variable
"""
import ccxt, time, psycopg2, datetime as dt, os, logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_symbols():
    symbols_env = os.getenv("SYMBOLS", "BTC/USDT")
    return [s.strip() for s in symbols_env.split(",")]

def connect_db():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "market"),
        user=os.getenv("POSTGRES_USER", "trader"),
        password=os.getenv("POSTGRES_PASSWORD", "s3cr3t"),
        host='db', port=5432
    )

def get_table_name(symbol):
    """Convert symbol to table name (e.g., BTC/USDT -> ohlcv_btc_usdt)"""
    return f"ohlcv_{symbol.replace('/', '_').replace('-', '_').lower()}"

def main():
    symbols = get_symbols()
    logger.info(f"Starting ingestor for symbols: {symbols}")
    
    kr = ccxt.kraken({'enableRateLimit': True})
    pg = connect_db()
    cur = pg.cursor()
    
    while True:
        try:
            for symbol in symbols:
                # Get symbol-specific table name (assumes table exists from init.sql)
                table_name = get_table_name(symbol)
                
                bars = kr.fetch_ohlcv(symbol, '1m', limit=1)
                for ts, o, h, l, c, v in bars:
                    cur.execute(f"""
                        INSERT INTO {table_name} VALUES (to_timestamp(%s/1000.0),%s,%s,%s,%s,%s)
                        ON CONFLICT (ts)
                        DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high,
                                     low=EXCLUDED.low, close=EXCLUDED.close, vol=EXCLUDED.vol
                    """, (ts, o, h, l, c, v))
                    logger.info(f"Inserted {symbol} bar into {table_name} at {dt.datetime.fromtimestamp(ts/1000)}")
            pg.commit()
            time.sleep(60 - dt.datetime.utcnow().second)
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()