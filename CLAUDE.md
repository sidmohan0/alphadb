````markdown
# claude.md
> **Purpose** – Feed this file into Claude (or any other code-gen agent) so it has *all* the context it needs to spin-up a self-hosted **TimescaleDB + Grafana “trading-lab” stack** for crypto-research.  
> The end-state is a local Docker Compose project that (a) persists data, (b) refreshes aggregates automatically, and (c) exposes dashboards at <http://localhost:3000>.

---

## 1  High-level goals
| # | Requirement | Acceptance test |
|---|-------------|-----------------|
| 1 | Postgres 16 with TimescaleDB 2.15 running in a container named **`tsdb`** | `docker exec tsdb psql -U trader -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"` returns `2.15` |
| 2 | Grafana OSS 12 in container **`grafana`** on port **3000** with the Timescale datasource pre-wired | Hitting `/api/datasources` returns JSON containing `"name":"Timescale (market)"` |
| 3 | Hypertable **`ohlcv_1m`** and continuous aggregate **`ohlcv_5m`** exist | `\dt+` in psql lists both tables |
| 4 | Example panel plotting close price from `ohlcv_5m` appears on default dashboard | Visiting <http://localhost:3000> shows a line chart without manual setup |
| 5 | All state stored on named Docker volumes (`tsdb-data` & `grafana-storage`) | `docker volume ls` lists them; removing containers preserves DB |

---

## 2  Stack overview
```mermaid
flowchart LR
  subgraph Docker_Network
    tsdb[(TimescaleDB<br>Postgres 16 + TS 2.15)]
    grafana[[Grafana OSS 12<br>dashboards]]
  end
  user((Host<br>localhost:5432/3000)) --- grafana
  script[[Python / Rust<br>data-ingestors]] --> tsdb
````

---

## 3  Environment variables (`.env`)

```
POSTGRES_USER=trader
POSTGRES_PASSWORD=s3cr3t
POSTGRES_DB=market
GF_SECURITY_ADMIN_PASSWORD=adminpw
```

---

## 4  `docker-compose.yml`

```yaml
version: "3.9"
services:
  db:
    image: timescale/timescaledb:pg16-ts2.15.0
    container_name: tsdb
    restart: unless-stopped
    env_file: .env
    environment:
      - TIMESCALE_TELEMETRY=off
    ports:
      - "5432:5432"
    volumes:
      - tsdb-data:/var/lib/postgresql/data

  grafana:
    image: grafana/grafana-oss:12.1.0
    container_name: grafana
    restart: unless-stopped
    env_file: .env
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GF_SECURITY_ADMIN_PASSWORD}
    ports:
      - "3000:3000"
    depends_on:
      - db
    volumes:
      - grafana-storage:/var/lib/grafana

volumes:
  tsdb-data:
  grafana-storage:
```

---

## 5  Database bootstrap SQL

Feed this once (e.g. `docker exec -i tsdb psql -U trader -d market < init.sql`):

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS ohlcv_1m (
  ts   TIMESTAMPTZ PRIMARY KEY,
  open  DOUBLE PRECISION,
  high  DOUBLE PRECISION,
  low   DOUBLE PRECISION,
  close DOUBLE PRECISION,
  vol   DOUBLE PRECISION
);

SELECT create_hypertable('ohlcv_1m', 'ts', chunk_time_interval => INTERVAL '1 day', if_not_exists=>true);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_5m
WITH (timescaledb.continuous)
AS
SELECT
  time_bucket('5 minutes', ts) AS bucket,
  first(open, ts)              AS open,
  max(high)                    AS high,
  min(low)                     AS low,
  last(close, ts)              AS close,
  sum(vol)                     AS vol
FROM ohlcv_1m
GROUP BY bucket;
```

---

## 6  Example Python ingestor (minute bars)

```python
"""
Run as:  docker exec -it tsdb psql market < schema.sql   # once
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
```

---

## 7  Grafana provisioning (optional but slick)

*File*: `provisioning/datasources/ds.yml`

```yaml
apiVersion: 1
datasources:
  - name: Timescale (market)
    type: postgres
    access: proxy
    user: ${POSTGRES_USER}
    secureJsonData:
      password: ${POSTGRES_PASSWORD}
    url: db:5432
    database: ${POSTGRES_DB}
    jsonData:
      sslmode: disable
      postgresVersion: 1200
      timescaledb: true
```

Mount `provisioning/` into `/etc/grafana/provisioning/` in the Grafana service.

---

## 8  CLI cheat-sheet

```bash
# spin up / shut down
docker compose up -d
docker compose down

# psql shell
docker exec -it tsdb psql -U trader -d market

# test continuous aggregate
SELECT * FROM ohlcv_5m ORDER BY bucket DESC LIMIT 3;
```

---

## 9  Next steps for Claude

1. **Generate**: `init.sql`, `ingest.py`, `provisioning` files exactly as above.
2. **Run**: `docker compose up -d` and verify acceptance tests 1-4.
3. **Return**: screenshot (or JSON) of Grafana API listing confirming datasource + dashboard.

> *If anything fails, output the error log and proposed fix, then retry.*

