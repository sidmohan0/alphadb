Below is a **copy-paste-ready “hello world” lab** that gets a self-hosted TimescaleDB instance and a Grafana UI running side-by-side in Docker Compose.  When you finish, you’ll have:

* a network-isolated Postgres 16 + TimescaleDB 2.15 container that persists to a local volume,
* Grafana OSS 12 listening on port 3000, already able to query Timescale, and
* a psql cheat-sheet for turning a plain OHLCV table into a hypertable and a continuous aggregate.

---

## 1  Prerequisites

| Tool              | Version (≥)                                                              | Test command             |
| ----------------- | ------------------------------------------------------------------------ | ------------------------ |
| Docker Engine     | 24                                                                       | `docker --version`       |
| Docker Compose v2 | bundled with Docker Desktop 4.29+ or `apt install docker-compose-plugin` | `docker compose version` |

> *No extra packages on the host—you’ll do everything in containers.*

---

## 2  Create a project folder

```bash
mkdir trading-lab && cd trading-lab
touch docker-compose.yml .env
```

Populate **.env** (git-ignore it later):

```dotenv
POSTGRES_USER=trader
POSTGRES_PASSWORD=s3cr3t
POSTGRES_DB=market
GF_SECURITY_ADMIN_PASSWORD=adminpw   # change in prod!
```

---

## 3  Write *docker-compose.yml*

```yaml
version: "3.9"
services:
  db:
    image: timescale/timescaledb:pg16-ts2.15.0   # latest LTS tag :contentReference[oaicite:0]{index=0}
    container_name: tsdb
    restart: unless-stopped
    env_file: .env
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
      - TIMESCALE_TELEMETRY=off
    ports:
      - "5432:5432"
    volumes:
      - tsdb-data:/var/lib/postgresql/data

  grafana:
    image: grafana/grafana-oss:12.1.0            # official OSS build :contentReference[oaicite:1]{index=1}
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

Spin it up:

```bash
docker compose up -d           # first run pulls images (~700 MB total)
docker compose logs -f db      # wait for “database system is ready”
```

---

## 4  Bootstrap TimescaleDB

```bash
docker exec -it tsdb psql -U $POSTGRES_USER -d $POSTGRES_DB
```

Inside `psql`:

```sql
-- 1) enable the extension once per database
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 2) raw OHLCV table (timestamps in milliseconds UTC)
CREATE TABLE ohlcv_1m (
  ts   TIMESTAMPTZ NOT NULL,
  open  DOUBLE PRECISION,
  high  DOUBLE PRECISION,
  low   DOUBLE PRECISION,
  close DOUBLE PRECISION,
  vol   DOUBLE PRECISION,
  PRIMARY KEY (ts)
);

-- 3) convert to hypertable (1-minute chunking)
SELECT create_hypertable('ohlcv_1m', 'ts', chunk_time_interval => INTERVAL '1 day');

-- 4) optional continuous aggregate for 5-minute bars
CREATE MATERIALIZED VIEW ohlcv_5m
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('5 minutes', ts)  AS bucket,
  first(open, ts)               AS open,
  max(high)                     AS high,
  min(low)                      AS low,
  last(close, ts)               AS close,
  sum(vol)                      AS vol
FROM ohlcv_1m
GROUP BY bucket;
```

> Hypertables let you ingest millions of rows/day with native partitioning; the continuous aggregate auto-refreshes in the background so Grafana can query 5 min data without scanning the raw minutes ([docs.timescale.com][1]).

---

## 5  Log in to Grafana

1. Open **[http://localhost:3000](http://localhost:3000)**.
2. User = `admin`, Password = `${GF_SECURITY_ADMIN_PASSWORD}` (from `.env`).
3. **Add ▼** → **Data sources** → **PostgreSQL**

   * Host = `tsdb:5432` (service name resolves via compose network)
   * Database = `market`, User/Pass as above
   * **TimescaleDB** slider → **ON** → **Save & test**.

Grafana now autocompletes `time_bucket()` and your hypertable names.

---

## 6  First dashboard

*Create → Dashboard → Add new panel →* query example:

```sql
SELECT
  bucket AS "time",
  close AS price
FROM ohlcv_5m
WHERE $__timeFilter(bucket)
ORDER BY bucket;
```

Choose a line chart, hit **Apply**—you’ve got a live price panel.

---

## 7  Ingesting data continuously

**Option A – local Python script (prototype):**

```python
import ccxt, time, psycopg2, datetime as dt
kr = ccxt.kraken({'enableRateLimit': True})
pg = psycopg2.connect("dbname=market user=trader password=s3cr3t host=localhost")
cur = pg.cursor()

while True:
    now = int(time.time() * 1000)
    bars = kr.fetch_ohlcv('BTC/USDT', '1m', limit=1)  # last minute
    for ts,o,h,l,c,v in bars:
        cur.execute(
            "INSERT INTO ohlcv_1m VALUES (to_timestamp(%s/1000.0),%s,%s,%s,%s,%s)"
            "ON CONFLICT (ts) DO UPDATE SET open=EXCLUDED.open,"
            " high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close, vol=EXCLUDED.vol",
            (ts,o,h,l,c,v)
        )
    pg.commit()
    time.sleep(60 - dt.datetime.utcnow().second)
```

Docker-ise later, or rewrite in Rust for a 24 × 7 WebSocket recorder.

**Option B – VectorBT bulk import (back-fill):**
Load your 90-day Parquet into a DataFrame and use `copy_expert` to ingest millions of rows per minute.

---

## 8  House-keeping tips

| Task                        | Command                                                       |
| --------------------------- | ------------------------------------------------------------- |
| **Back-up**                 | `docker exec tsdb pg_dump -Fc -U trader market > daily.dump`  |
| **Upgrade Timescale image** | `docker compose pull db && docker compose up -d --no-deps db` |
| **Enable auth for Grafana** | set `GF_AUTH_DISABLE_LOGIN_FORM=false`, use GitHub OAuth.     |
| **Retention policy**        | `SELECT add_retention_policy('ohlcv_1m', INTERVAL '1 year');` |

---

### You’re ready to hack

Now you’ve got a local **time-series lab** that can:

* ingest OHLCV ticks in real time,
* aggregate them continuously, and
* let Grafana plot anything from raw candles to model P\&L—all without leaving Docker.

From here, drop your feature-engineering notebooks in the same repo and point them at `postgresql://trader:s3cr3t@localhost:5432/market`.  Happy building—and enjoy that first graph lighting up! 🟢📈

[1]: https://docs.timescale.com/self-hosted/latest/install/installation-docker/?utm_source=chatgpt.com "Install TimescaleDB on Docker - Timescale documentation"
