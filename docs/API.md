# API Documentation

Database schema, query examples, and API reference for AlphaDB.

## 📊 Database Schema

### Tables Overview

| Table | Type | Description | Retention |
|-------|------|-------------|-----------|
| `ohlcv_1m` | Hypertable | 1-minute OHLCV data | Unlimited |
| `ohlcv_5m` | Continuous Aggregate | 5-minute OHLCV data | Auto-updated |

### Table Details

#### `ohlcv_1m` (Hypertable)
Primary table for storing 1-minute OHLCV (Open, High, Low, Close, Volume) data.

```sql
Column |           Type           | Description
-------|--------------------------|---------------------------
ts     | timestamptz              | Timestamp (Primary Key)
open   | double precision         | Opening price
high   | double precision         | Highest price in period
low    | double precision         | Lowest price in period  
close  | double precision         | Closing price
vol    | double precision         | Volume (in BTC)
```

**Partitioning**: Automatic 1-day chunks
**Indexes**: Primary key on `ts`, optimized for time-range queries

#### `ohlcv_5m` (Continuous Aggregate)
Materialized view aggregating 1-minute data into 5-minute intervals.

```sql
Column |           Type           | Description
-------|--------------------------|---------------------------
bucket | timestamptz              | 5-minute time bucket
open   | double precision         | First opening price
high   | double precision         | Highest price in 5min
low    | double precision         | Lowest price in 5min
close  | double precision         | Last closing price
vol    | double precision         | Total volume (in BTC)
```

**Update Policy**: Real-time, updates as new data arrives

## 🔍 Query Examples

### Basic Queries

#### Get Latest Price
```sql
SELECT ts, close 
FROM ohlcv_1m 
ORDER BY ts DESC 
LIMIT 1;
```

#### Get Last 24 Hours of 5-minute Data
```sql
SELECT bucket, open, high, low, close, vol
FROM ohlcv_5m 
WHERE bucket >= NOW() - INTERVAL '24 hours'
ORDER BY bucket DESC;
```

#### Calculate Price Change
```sql
WITH recent_prices AS (
  SELECT close, 
         LAG(close) OVER (ORDER BY ts) as prev_close
  FROM ohlcv_1m 
  ORDER BY ts DESC 
  LIMIT 2
)
SELECT 
  close as current_price,
  prev_close as previous_price,
  close - prev_close as price_change,
  ROUND(((close - prev_close) / prev_close * 100)::numeric, 2) as price_change_pct
FROM recent_prices 
WHERE prev_close IS NOT NULL;
```

### Analytics Queries

#### Hourly Trading Volume
```sql
SELECT 
  time_bucket('1 hour', ts) as hour,
  SUM(vol) as hourly_volume,
  COUNT(*) as trades_count
FROM ohlcv_1m 
WHERE ts >= NOW() - INTERVAL '24 hours'
GROUP BY hour 
ORDER BY hour DESC;
```

#### Price Volatility (Standard Deviation)
```sql
SELECT 
  time_bucket('1 hour', ts) as hour,
  STDDEV(close) as price_volatility,
  MIN(low) as hour_low,
  MAX(high) as hour_high
FROM ohlcv_1m 
WHERE ts >= NOW() - INTERVAL '24 hours'
GROUP BY hour 
ORDER BY hour DESC;
```

#### Moving Averages
```sql
SELECT 
  ts,
  close,
  AVG(close) OVER (
    ORDER BY ts 
    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
  ) as ma_20,
  AVG(close) OVER (
    ORDER BY ts 
    ROWS BETWEEN 49 PRECEDING AND CURRENT ROW  
  ) as ma_50
FROM ohlcv_1m 
WHERE ts >= NOW() - INTERVAL '4 hours'
ORDER BY ts DESC;
```

### Performance Queries

#### Data Statistics
```sql
-- Count records and time range
SELECT 
  COUNT(*) as total_records,
  MIN(ts) as earliest_data,
  MAX(ts) as latest_data,
  MAX(ts) - MIN(ts) as data_span
FROM ohlcv_1m;

-- Data gaps detection
SELECT 
  ts,
  LAG(ts) OVER (ORDER BY ts) as prev_ts,
  ts - LAG(ts) OVER (ORDER BY ts) as gap
FROM ohlcv_1m 
WHERE ts >= NOW() - INTERVAL '2 hours'
ORDER BY gap DESC NULLS LAST
LIMIT 10;
```

#### Continuous Aggregate Health
```sql
-- Check continuous aggregate lag
SELECT 
  view_name,
  completed_threshold,
  materialization_hypertable
FROM timescaledb_information.continuous_aggregates;

-- Manual refresh if needed
CALL refresh_continuous_aggregate('ohlcv_5m', NULL, NULL);
```

## 🔌 Connection Examples

### Python (psycopg2)
```python
import psycopg2
import pandas as pd

# Connection
conn = psycopg2.connect(
    host='localhost',
    port=5432,
    database='market',
    user='trader',
    password='your_password'
)

# Query recent data
query = """
SELECT bucket, open, high, low, close, vol
FROM ohlcv_5m 
WHERE bucket >= NOW() - INTERVAL '1 hour'
ORDER BY bucket DESC;
"""

df = pd.read_sql(query, conn)
print(df.head())
```

### Python (SQLAlchemy)
```python
from sqlalchemy import create_engine
import pandas as pd

# Connection string
engine = create_engine('postgresql://trader:password@localhost:5432/market')

# Query with pandas
df = pd.read_sql_query("""
    SELECT ts, close, vol
    FROM ohlcv_1m 
    WHERE ts >= NOW() - INTERVAL '30 minutes'
    ORDER BY ts
""", engine)

# Calculate returns
df['returns'] = df['close'].pct_change()
```

### Node.js (pg)
```javascript
const { Client } = require('pg');

const client = new Client({
  host: 'localhost',
  port: 5432,
  database: 'market',
  user: 'trader',
  password: 'your_password'
});

async function getLatestPrice() {
  await client.connect();
  
  const result = await client.query(`
    SELECT ts, close 
    FROM ohlcv_1m 
    ORDER BY ts DESC 
    LIMIT 1
  `);
  
  console.log('Latest BTC price:', result.rows[0]);
  await client.end();
}
```

## 📈 Grafana Query Examples

### Panel Queries

#### Candlestick Chart
```sql
SELECT
  bucket AS "time",
  open AS "Open",
  high AS "High", 
  low AS "Low",
  close AS "Close"
FROM ohlcv_5m
WHERE $__timeFilter(bucket)
ORDER BY bucket
```

#### Volume Bars
```sql
SELECT
  bucket AS "time",
  vol AS "Volume (BTC)"
FROM ohlcv_5m
WHERE $__timeFilter(bucket)
ORDER BY bucket
```

#### Price Line Chart
```sql
SELECT
  ts AS "time",
  close AS "BTC/USDT"
FROM ohlcv_1m
WHERE $__timeFilter(ts)
ORDER BY ts
```

### Alert Queries

#### Price Change Alert
```sql
WITH price_change AS (
  SELECT 
    close,
    LAG(close, 60) OVER (ORDER BY ts) as price_1h_ago
  FROM ohlcv_1m 
  ORDER BY ts DESC 
  LIMIT 1
)
SELECT 
  ABS((close - price_1h_ago) / price_1h_ago * 100) as change_pct
FROM price_change
WHERE price_1h_ago IS NOT NULL;
```

## 🛠️ Maintenance

### Database Maintenance

#### Compression (for older data)
```sql
-- Enable compression on chunks older than 7 days
SELECT add_compression_policy('ohlcv_1m', INTERVAL '7 days');

-- Manual compression
SELECT compress_chunk(chunk)
FROM timescaledb_information.chunks 
WHERE hypertable_name = 'ohlcv_1m' 
  AND range_end < NOW() - INTERVAL '7 days';
```

#### Retention Policy
```sql
-- Drop data older than 1 year
SELECT add_retention_policy('ohlcv_1m', INTERVAL '1 year');
```

#### Statistics Update
```sql
-- Update table statistics for better query planning
ANALYZE ohlcv_1m;
ANALYZE ohlcv_5m;
```

### Backup and Restore

#### Backup
```bash
# Full database backup
docker exec tsdb pg_dump -U trader market > backup.sql

# Table-specific backup
docker exec tsdb pg_dump -U trader -t ohlcv_1m market > ohlcv_backup.sql
```

#### Restore
```bash
# Restore database
docker exec -i tsdb psql -U trader market < backup.sql
```

## 🔍 Monitoring Queries

### System Health
```sql
-- Check hypertable stats
SELECT * FROM timescaledb_information.hypertables;

-- Check chunk info
SELECT 
  chunk_name,
  range_start,
  range_end,
  is_compressed
FROM timescaledb_information.chunks 
WHERE hypertable_name = 'ohlcv_1m'
ORDER BY range_start DESC 
LIMIT 10;
```

### Data Quality
```sql
-- Check for duplicate timestamps
SELECT ts, COUNT(*) 
FROM ohlcv_1m 
GROUP BY ts 
HAVING COUNT(*) > 1;

-- Check data freshness
SELECT 
  MAX(ts) as latest_data,
  NOW() - MAX(ts) as data_lag,
  CASE 
    WHEN NOW() - MAX(ts) < INTERVAL '5 minutes' THEN 'HEALTHY'
    WHEN NOW() - MAX(ts) < INTERVAL '15 minutes' THEN 'WARNING' 
    ELSE 'STALE'
  END as status
FROM ohlcv_1m;
```

## 📚 Resources

- [TimescaleDB Documentation](https://docs.timescale.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Grafana Query Documentation](https://grafana.com/docs/grafana/latest/panels/query-a-data-source/)
- [CCXT Documentation](https://docs.ccxt.com/)

---

**Next**: See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues and solutions.