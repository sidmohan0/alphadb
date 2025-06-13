### Implementation Plan – `features_1m` **continuous-aggregate view**

*(computes log-returns, volume z-score, VWAP gap, Parkinson volatility for every 1-minute bucket and keeps itself fresh once per minute)*

---

## 0 ️⃣  Preconditions

| Check                              | Command                                               | Expect                           |
| ---------------------------------- | ----------------------------------------------------- | -------------------------------- |
| TimescaleDB ext                    | `\dx`                                                 | `timescaledb` present            |
| Toolkit ext (optional but easiest) | `CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit;` | success                          |
| Base hypertable                    | `\d ohlcv_1m`                                         | `ts` PK, one-minute data flowing |

*(Toolkit lets us use `moving_avg`, `moving_stddev` and keeps SQL terse.  Without it you’d fall back to window functions over a second CA layer.)*

---

## 1 ️⃣  Decide feature formulas

| Feature            | Formula (1-min bucket)                                                                 |
| ------------------ | -------------------------------------------------------------------------------------- |
| **log\_return**    | `ln(last(close,ts)/lag(last(close,ts)) over (order by bucket))`                        |
| **volume\_z**      | `(vol - ma_vol_1d) / std_vol_1d` where `ma_vol_1d = moving_avg(vol, INTERVAL '1 day')` |
| **vwap\_gap**      | `last(close,ts) - (sum(price*vol)/sum(vol))` using mid-bar VWAP\*                      |
| **parkinson\_vol** | `0.5 * POWER(ln(max(high)/min(low)),2)`                                                |

\*We lack per-trade price, so we approximate VWAP with weighted OHLC:
`price ≈ (open+high+low+close)/4`.

---

## 2 ️⃣  SQL – continuous aggregate

```sql
------------------  Enable toolkit if not done  ------------------
CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit;

------------------  CA view  ------------------------------------
CREATE MATERIALIZED VIEW features_1m
WITH (timescaledb.continuous)
AS
SELECT
    bucket                                       -- TIMESTAMPTZ
  , last_close
  , ln(last_close / lag(last_close)
        OVER (ORDER BY bucket))          AS log_return
  , vol
  , toolkit_experimental.moving_avg(vol,  INTERVAL '1 day')   OVER w AS ma_vol_1d
  , toolkit_experimental.moving_stddev(vol, INTERVAL '1 day') OVER w AS std_vol_1d
  , CASE WHEN toolkit_experimental.moving_stddev(vol, INTERVAL '1 day') OVER w = 0
         THEN NULL
         ELSE (vol
               - toolkit_experimental.moving_avg(vol,  INTERVAL '1 day') OVER w)
              / toolkit_experimental.moving_stddev(vol, INTERVAL '1 day') OVER w
    END                                           AS volume_z
  , last_close
    - ( (open+high+low+close)/4 )                 AS vwap_gap          -- minute proxy
  , 0.5 * POWER( ln(high/low) , 2)                AS parkinson_vol
FROM (
    SELECT
        time_bucket('1 minute', ts)                  AS bucket
      , first(open,  ts)                             AS open
      , max(high)                                    AS high
      , min(low)                                     AS low
      , last(close, ts)                              AS close
      , sum(vol)                                     AS vol
      , last(close, ts)                              AS last_close
    FROM   ohlcv_1m
    GROUP  BY bucket
) AS bar
WINDOW w AS (ORDER BY bucket ROWS BETWEEN 1439 PRECEDING AND CURRENT ROW);
```

*Notes*

* We create an **inner sub-query** that guarantees one bar per minute even if the WS recorder later starts writing sub-minute ticks.
* `moving_avg/stddev` give us running 1-day stats (\~1440 rows).
* `WITH (timescaledb.continuous)` marks it as a CA; Timescale materialises results in background chunks.

---

## 3 ️⃣  Continuous-aggregate refresh policy

```sql
SELECT add_continuous_aggregate_policy(
  'features_1m',
  start_offset      => INTERVAL '1 hour',      -- backfill safety net
  end_offset        => INTERVAL '1 minute',    -- keep 59 s behind realtime
  schedule_interval => INTERVAL '1 minute'     -- job frequency
);
```

Timescale’s job runner now calls *fast-refresh* each minute—no pg\_cron needed.

---

## 4 ️⃣  Helpful indexes

```sql
CREATE INDEX IF NOT EXISTS features_1m_bucket_idx
  ON features_1m (bucket DESC);

-- optional: narrow columns used most in ML queries
CREATE INDEX IF NOT EXISTS features_1m_symbol_idx
  ON features_1m (symbol, bucket DESC);  -- if symbol column added later
```

---

## 5 ️⃣  Validation steps

| Test                                                                            | Expected                         |
| ------------------------------------------------------------------------------- | -------------------------------- |
| `SELECT COUNT(*) FROM features_1m WHERE bucket > now()-'10 minutes'::interval;` | ≥ 9 rows                         |
| `SELECT * FROM features_1m ORDER BY bucket DESC LIMIT 3;`                       | non-NULL log\_return & volume\_z |
| Grafana panel on `volume_z`                                                     | updates at T+60 s; no flat gaps  |

---

## 6 ️⃣  Integration

* **Notebooks / VectorBT:**

  ```python
  q = "SELECT bucket, log_return, volume_z, vwap_gap, parkinson_vol \
       FROM features_1m \
       WHERE bucket BETWEEN %s AND %s"
  df = pd.read_sql(q, conn, params=[start, end])
  ```
* **Model-API Feature Fetcher:**
  Inside `FastAPI`, query the latest row:

  ```sql
  SELECT * FROM features_1m
  ORDER BY bucket DESC
  LIMIT 1;
  ```
* **Grafana:**
  Add a Postgres panel – query example:

  ```sql
  SELECT bucket AS "time", volume_z
  FROM features_1m
  WHERE $__timeFilter(bucket);
  ```

---

## 7 ️⃣  Maintenance & edge-cases

| Issue                                               | Mitigation                                                                                                               |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Late-arriving ticks** shift OHLCV                 | Policy’s `start_offset '1 hour'` lets fast-refresh re-compute last hour each run.                                        |
| **WS outage** (minute gaps)                         | REST back-fill script will insert missing rows; CA job automatically recomputes.                                         |
| **1-day look-back causes NULL for first 1440 rows** | Acceptable; ML can `fillna(0)` or wait until day-one.                                                                    |
| **Toolkit not installed**                           | Replace moving\_avg / stddev with:  <br>`avg(vol) OVER w`, `stddev_pop(vol) over w`  – same window spec; CA still valid. |

---

### TL;DR sequence

1. `psql -f feature_ca.sql` (contains steps 1-3).
2. Verify counts & Grafana panel.
3. Point model code at `features_1m` view.

Feature pipeline done—your ML loop now reads *clean, auto-rolling, minute-fresh* signals with zero cron scripts. 🎛️🟢
