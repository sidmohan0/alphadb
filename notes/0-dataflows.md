| Task | Tool / File | Done |
|------|------------|------|
| Convert the tiny ingest.py into a daemon (systemd service or Docker sidecar). | docker/Dockerfile + docker-compose.yml | ✅ |
| Add ETH/USDT & any other high-volume pairs; store per-pair tables (ohlcv_btc, ohlcv_eth). | SYMBOLS=BTC/USDT,ETH/USDT in docker-compose.yml | ✅ |
| Write a WebSocket recorder (Rust or Python) for tick-level trades ➜ table trades. | gateway/ (full Rust implementation) | ✅ |
| Schedule daily back-fills in case the feed dies (cron + CCXT). | scripts/backfill.sh | ☐ |
| Continuous aggregate for 5-minute and 1-hour bars. | | ☐ |