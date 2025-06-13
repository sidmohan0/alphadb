| Component | Description | Status |
|-----------|-------------|--------|
| SQL View | `features_1m` materialized view containing z-scores, log-returns, VWAP gap, Parkinson volatility | [ ] |
| Refresh | `ALTER MATERIALIZED VIEW ... REFRESH FAST START` every minute | [ ] |
| Analysis | VectorBT notebook pulling `SELECT * FROM features_1m WHERE ts BETWEEN ...` | [ ] |
| Storage | Persist engineered features to `features.parquet` for faster prototyping | [ ] |
| Monitoring | Grafana dashboard with panels:<br>- Missing bars per hour<br>- Volume z-score distribution | [ ] |