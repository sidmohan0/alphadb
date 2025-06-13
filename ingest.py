"""
Run as:  docker exec -it tsdb psql market < init.sql   # once
        python ingest.py                                 # continuous
"""
import ccxt, time, psycopg2, datetime as dt, os

kr = ccxt.kraken({'enableRateLimit': True})
pg = psycopg2.connect(
    dbname='market',
    user=os.getenv("POSTGRES_USER", "trader"),
    password=os.getenv("POSTGRES_PASSWORD", "s3cr3t"),
    host='localhost', port=5432
)
cur = pg.cursor()

while True:
    bars = kr.fetch_ohlcv('BTC/USDT', '1m', limit=1)
    for ts, o, h, l, c, v in bars:
        cur.execute(
            """INSERT INTO ohlcv_1m VALUES (to_timestamp(%s/1000.0),%s,%s,%s,%s,%s)
               ON CONFLICT (ts)
               DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high,
                             low=EXCLUDED.low, close=EXCLUDED.close, vol=EXCLUDED.vol""",
            (ts, o, h, l, c, v)
        )
    pg.commit()
    time.sleep(60 - dt.datetime.utcnow().second)