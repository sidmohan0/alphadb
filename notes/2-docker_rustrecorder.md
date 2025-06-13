### Plugging the WebSocket recorder into your **Docker-Compose** stack

*(so everything still comes up with one `docker compose up -d`)*

---

## 1  Add the recorder codebase (if you haven’t already)

```
trading-lab/
├─ docker-compose.yml
├─ .env
├─ db/              # optional init SQL
├─ grafana/         # provisioning files
└─ gateway/
   ├─ Cargo.toml
   ├─ src/
   │   └─ main.rs
   ├─ config/       # config.toml for pairs, batch size, etc.
   └─ Dockerfile    # build instructions (next section)
```

---

## 2  Create `gateway/Dockerfile`  ( multi-stage )

```dockerfile
# ---------- build stage ----------
FROM rust:1.78 as builder
WORKDIR /app
# cache deps first
COPY gateway/Cargo.toml gateway/Cargo.lock ./
RUN cargo fetch
COPY gateway/src ./src
RUN cargo build --release

# ---------- runtime stage ----------
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y libpq5 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/ws_recorder /usr/local/bin/ws_recorder
# copy pair/DB config in at runtime; keep image generic
ENTRYPOINT ["/usr/local/bin/ws_recorder"]
```

---

## 3  Extend `docker-compose.yml`

```yaml
version: "3.9"
services:
  db:
    # … existing TimescaleDB service …

  grafana:
    # … existing Grafana service …

  ws_recorder:
    build: ./gateway              # or "image: sid/ws_recorder:latest" once you push
    container_name: ws_recorder
    restart: unless-stopped
    env_file: .env
    environment:
      # DB creds picked up from .env
      CONFIG=/config/config.toml   # path inside container
    volumes:
      - ./gateway/config:/config:ro
    depends_on:
      - db
    # expose Prometheus metrics
    ports:
      - "9187:9187"                # :9187/metrics
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:9187/metrics"]
      interval: 30s
      timeout: 5s
      retries: 3
```

**Why volumes?** - lets you tweak `config.toml` without rebuilding the image.

---

## 4  Update `.env` (with the DB creds the recorder will use)

```dotenv
POSTGRES_USER=trader
POSTGRES_PASSWORD=s3cr3t
POSTGRES_DB=market
WS_RECORDER__VENUE=kraken          # optional override via env
```

The recorder reads these via `std::env`.

---

## 5  Add a Prometheus scrape job (optional)

If you already scrape Grafana/Prometheus in another stack, target `localhost:9187`.

---

## 6  Build & launch everything

```bash
docker compose build ws_recorder          # first-time build (or --build on up)
docker compose up -d                      # spins db, grafana, recorder
docker compose logs -f ws_recorder        # watch connect / insert messages
```

*You should see lines like*
`INFO subscribed BTC/USDT | msgs=60/s lag=42 ms`
and row counts climbing in `trades`.

---

## 7  Common dev loop

| Task                      | Command                                                                         |        |
| ------------------------- | ------------------------------------------------------------------------------- | ------ |
| Change Rust code          | edit → `docker compose build ws_recorder` → `docker compose up -d ws_recorder`  |        |
| Change pairs / batch size | edit `gateway/config/config.toml` → `docker compose restart ws_recorder`        |        |
| Tail metrics              | \`curl -s [http://localhost:9187/metrics](http://localhost:9187/metrics)        | head\` |
| Verify rows               | `docker exec -it tsdb psql -U $POSTGRES_USER -c "SELECT COUNT(*) FROM trades;"` |        |

---

### FAQ

| Q                                               | A                                                                                                                                                                   |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Does this replace the minute-REST ingester?** | No.  Keep the REST script for back-fills / historical pulls.  The recorder is your real-time fire-hose.                                                             |
| **Will containers start in the right order?**   | `depends_on:` guarantees Timescale is reachable before the recorder connects.                                                                                       |
| **Where are logs stored?**                      | Stdout → `docker compose logs ws_recorder`.  Pipe to Loki if desired.                                                                                               |
| **What if I add more venues?**                  | Mount additional `config.toml` files and spin up another recorder service (`ws_recorder_binance`, etc.) or let one binary spawn multiple tasks per venue—your call. |

---

Now **all** services—database, dashboards, minute-bar ingester, and tick-feed recorder—live under the same Compose umbrella.
One command boots the lab, one command tears it down.  Happy shipping! 🚢🦀📈
