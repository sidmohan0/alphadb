# Setup Guide

Complete setup instructions for the AlphaDB.

## 📋 Prerequisites

### System Requirements
- **Docker**: 20.10+ and Docker Compose v2
- **Python**: 3.8+ (for data ingestion scripts)
- **RAM**: 8GB recommended (4GB minimum)
- **Storage**: 10GB free space minimum
- **OS**: Linux, macOS, or Windows with WSL2

### Verify Prerequisites
```bash
# Check Docker
docker --version
docker compose version

# Check Python
python3 --version
pip3 --version
```

## 🚀 Installation

### 1. Clone Repository
```bash
git clone https://github.com/your-username/alphadb.git
cd alphadb
```

### 2. Environment Configuration
```bash
# Copy environment template
cp .env.example .env

# Edit with your preferred passwords
nano .env  # or vim, code, etc.
```

**Required Environment Variables:**
```bash
POSTGRES_USER=trader                    # Database username
POSTGRES_PASSWORD=your_secure_password  # Database password (change this!)
POSTGRES_DB=market                      # Database name
GF_SECURITY_ADMIN_PASSWORD=admin_pass   # Grafana admin password (change this!)
```

### 3. Launch Docker Stack
```bash
# Start all services
docker compose up -d

# Verify services are running
docker compose ps
```

Expected output:
```
NAME      SERVICE   STATUS    PORTS
grafana   grafana   running   0.0.0.0:3000->3000/tcp
tsdb      db        running   0.0.0.0:5432->5432/tcp
```

### 4. Initialize Database
```bash
# Create tables and hypertables
docker exec -i tsdb psql -U trader -d market < init.sql
```

Expected output:
```
CREATE EXTENSION
CREATE TABLE
   create_hypertable   
-----------------------
 (1,public,ohlcv_1m,t)
CREATE MATERIALIZED VIEW
```

### 5. Install Python Dependencies
```bash
# Install required packages
pip3 install ccxt psycopg2-binary

# Verify installation
python3 -c "import ccxt, psycopg2; print('Dependencies installed successfully')"
```

### 6. Start Data Ingestion
```bash
# Run in background (using screen/tmux recommended)
python3 scripts/ingest.py

# Or run in screen session
screen -S crypto-ingest
python3 scripts/ingest.py
# Ctrl+A, D to detach
```

### 7. Access Grafana
1. Open browser to http://localhost:3000
2. Login with:
   - **Username**: `admin`
   - **Password**: Your `GF_SECURITY_ADMIN_PASSWORD` from `.env`
3. Navigate to dashboards → "BTC/USDT Trading Dashboard"

## ✅ Verification

### Database Connection
```bash
# Test database connection
docker exec -it tsdb psql -U trader -d market

# Check tables exist
\dt+

# Check data is being ingested
SELECT COUNT(*) FROM ohlcv_1m;
SELECT * FROM ohlcv_1m ORDER BY ts DESC LIMIT 5;
```

### Grafana Datasource
```bash
# Test Grafana API
curl -u admin:your_grafana_password http://localhost:3000/api/datasources
```

### Data Ingestion
```bash
# Check ingestion logs
screen -r crypto-ingest  # if using screen

# Monitor data growth
watch "docker exec tsdb psql -U trader -d market -c 'SELECT COUNT(*) FROM ohlcv_1m;'"
```

## 🛠️ Customization

### Adding More Exchanges
Edit `scripts/ingest.py` to add additional exchanges:
```python
# Add new exchange
binance = ccxt.binance({'enableRateLimit': True})

# Fetch data from multiple sources
exchanges = [
    ('kraken', ccxt.kraken({'enableRateLimit': True})),
    ('binance', ccxt.binance({'enableRateLimit': True}))
]
```

### Custom Dashboards
1. Create dashboard in Grafana UI
2. Export JSON via Settings → JSON Model
3. Save to `grafana/dashboards/`
4. Add to `grafana/dashboards/dashboard.yml`

### Database Tuning
For high-volume data, consider these PostgreSQL settings in `docker-compose.yml`:
```yaml
environment:
  - POSTGRES_SHARED_PRELOAD_LIBRARIES=timescaledb
  - POSTGRES_MAX_CONNECTIONS=200
  - POSTGRES_SHARED_BUFFERS=256MB
  - POSTGRES_EFFECTIVE_CACHE_SIZE=1GB
```

## 🔧 Advanced Configuration

### Custom Time Aggregations
Add more continuous aggregates in `init.sql`:
```sql
-- 15-minute aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_15m
WITH (timescaledb.continuous)
AS
SELECT
  time_bucket('15 minutes', ts) AS bucket,
  first(open, ts)  AS open,
  max(high)        AS high,
  min(low)         AS low,
  last(close, ts)  AS close,
  sum(vol)         AS vol
FROM ohlcv_1m
GROUP BY bucket;
```

### SSL/TLS Configuration
For production deployment, configure SSL:
```yaml
# In docker-compose.yml
grafana:
  environment:
    - GF_SERVER_PROTOCOL=https
    - GF_SERVER_CERT_FILE=/etc/ssl/certs/grafana.crt
    - GF_SERVER_CERT_KEY=/etc/ssl/private/grafana.key
```

## 🚨 Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues and solutions.

## 📞 Support

- **GitHub Issues**: Bug reports and feature requests
- **Discussions**: Questions and community support
- **Documentation**: This guide and [API.md](API.md)

## 🔄 Updates

### Updating the Stack
```bash
# Pull latest changes
git pull origin main

# Update Docker images
docker compose pull

# Restart services
docker compose down
docker compose up -d
```

### Database Migrations
Check for schema updates in `init.sql` and apply manually if needed.

---

**Next Steps**: Check out [API.md](API.md) for database schema details and query examples.