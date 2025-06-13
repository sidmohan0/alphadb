# Troubleshooting Guide

Common issues and solutions for AlphaDB.

## 🚨 Common Issues

### Docker & Container Issues

#### ❌ Docker Compose Fails to Start
**Symptoms:**
- Services fail to start
- Port binding errors
- Volume mount issues

**Solutions:**
```bash
# Check if ports are already in use
sudo netstat -tlnp | grep :3000
sudo netstat -tlnp | grep :5432

# Stop conflicting services
sudo systemctl stop postgresql  # if running locally
sudo systemctl stop grafana-server  # if running locally

# Clean up Docker state
docker compose down -v
docker system prune -f
docker volume prune -f

# Restart Docker daemon (if needed)
sudo systemctl restart docker
```

#### ❌ Container Memory Issues
**Symptoms:**
- Services randomly stopping
- OOM (Out of Memory) errors
- Poor performance

**Solutions:**
```bash
# Check container memory usage
docker stats

# Increase Docker memory limits (Docker Desktop)
# Settings → Resources → Memory → Increase to 8GB+

# Add memory limits to docker-compose.yml
services:
  db:
    mem_limit: 2g
  grafana:
    mem_limit: 1g
```

### Database Issues

#### ❌ Cannot Connect to Database
**Symptoms:**
- `psql: error: connection refused`
- Python scripts fail with connection errors
- Grafana shows database connection errors

**Diagnostics:**
```bash
# Check if database container is running
docker compose ps

# Check database logs
docker compose logs db

# Test connection manually
docker exec -it tsdb psql -U trader -d market

# Check if database is accepting connections
docker exec tsdb pg_isready -U trader
```

**Solutions:**
```bash
# Restart database service
docker compose restart db

# Check environment variables
cat .env

# Verify database initialization
docker exec tsdb psql -U trader -d market -c "\dt+"

# Reset database (WARNING: loses all data)
docker compose down -v
docker volume rm alphadb_tsdb-data
docker compose up -d
docker exec -i tsdb psql -U trader -d market < init.sql
```

#### ❌ TimescaleDB Extension Not Found
**Symptoms:**
- `ERROR: extension "timescaledb" is not available`
- Hypertable creation fails

**Solutions:**
```bash
# Check TimescaleDB version
docker exec tsdb psql -U trader -c "SELECT * FROM pg_available_extensions WHERE name='timescaledb';"

# Verify correct image
docker exec tsdb psql -U trader -c "SELECT version();"

# Should show TimescaleDB in the output
# If not, check docker-compose.yml image version
```

#### ❌ Data Not Appearing in Tables
**Symptoms:**
- `SELECT COUNT(*) FROM ohlcv_1m;` returns 0
- No data in Grafana dashboards
- Ingestion script seems to run but no data stored

**Diagnostics:**
```bash
# Check if tables exist
docker exec tsdb psql -U trader -d market -c "\dt+"

# Check table schema
docker exec tsdb psql -U trader -d market -c "\d ohlcv_1m"

# Check continuous aggregate
docker exec tsdb psql -U trader -d market -c "SELECT * FROM ohlcv_5m LIMIT 5;"

# Check for transaction locks
docker exec tsdb psql -U trader -d market -c "SELECT * FROM pg_locks WHERE granted = false;"
```

**Solutions:**
```bash
# Re-run database initialization
docker exec -i tsdb psql -U trader -d market < init.sql

# Check ingestion script logs
python3 scripts/ingest.py  # run in foreground to see errors

# Manually insert test data
docker exec tsdb psql -U trader -d market -c "
INSERT INTO ohlcv_1m VALUES 
(NOW(), 50000, 50100, 49900, 50050, 0.1);"

# Refresh continuous aggregate
docker exec tsdb psql -U trader -d market -c "
CALL refresh_continuous_aggregate('ohlcv_5m', NULL, NULL);"
```

### Grafana Issues

#### ❌ Cannot Access Grafana Web Interface
**Symptoms:**
- Browser shows "This site can't be reached"
- Connection timeout at localhost:3000

**Solutions:**
```bash
# Check if Grafana container is running
docker compose ps grafana

# Check Grafana logs
docker compose logs grafana

# Verify port mapping
docker port grafana 3000

# Test with curl
curl -I http://localhost:3000

# If using different host/port
# Update GF_SERVER_HTTP_ADDR and GF_SERVER_HTTP_PORT in .env
```

#### ❌ Grafana Login Issues
**Symptoms:**
- "Invalid username or password"
- Cannot access admin account

**Solutions:**
```bash
# Verify admin password in .env
cat .env | grep GF_SECURITY_ADMIN_PASSWORD

# Reset admin password
docker exec grafana grafana-cli admin reset-admin-password newpassword

# Or reset via container restart
docker compose down
# Edit .env with new password
docker compose up -d
```

#### ❌ Datasource Connection Failed
**Symptoms:**
- "database connection failed" in Grafana
- Red status on datasource page

**Diagnostics:**
```bash
# Test datasource from Grafana container
docker exec grafana nc -zv db 5432

# Check datasource configuration
curl -u admin:yourpassword http://localhost:3000/api/datasources
```

**Solutions:**
```bash
# Verify database credentials match .env
# Check grafana/datasources/ds.yml

# Restart both services
docker compose restart db grafana

# Manually test database connection
docker exec grafana psql -h db -U trader -d market -c "SELECT 1;"
```

#### ❌ Dashboard Not Loading
**Symptoms:**
- Empty dashboard
- "No data" errors
- Panels show error messages

**Solutions:**
```bash
# Check dashboard provisioning
docker exec grafana ls -la /etc/grafana/provisioning/dashboards/

# Verify dashboard JSON syntax
docker exec grafana cat /etc/grafana/provisioning/dashboards/btc-dashboard.json | jq .

# Check query syntax in Grafana
# Go to Explore → Run queries manually

# Restart Grafana to reload provisioning
docker compose restart grafana
```

### Data Ingestion Issues

#### ❌ Python Script Errors
**Symptoms:**
- Import errors for ccxt or psycopg2
- Exchange API errors
- Connection refused errors

**Solutions:**
```bash
# Install/reinstall dependencies
pip3 install --upgrade ccxt psycopg2-binary

# Test exchange connection
python3 -c "import ccxt; kr = ccxt.kraken(); print(kr.fetch_ticker('BTC/USDT'))"

# Test database connection
python3 -c "
import psycopg2
conn = psycopg2.connect(
    host='localhost', port=5432,
    database='market', user='trader', 
    password='s3cr3t'
)
print('Database connection successful')
"

# Run script with debugging
python3 -u scripts/ingest.py
```

#### ❌ Exchange API Rate Limits
**Symptoms:**
- "Rate limit exceeded" errors
- Temporary connection bans
- Missing data points

**Solutions:**
```python
# In scripts/ingest.py, increase delays
time.sleep(120)  # Wait 2 minutes instead of 60 seconds

# Add error handling
try:
    bars = kr.fetch_ohlcv('BTC/USDT', '1m', limit=1)
except ccxt.NetworkError as e:
    print(f"Network error: {e}")
    time.sleep(300)  # Wait 5 minutes
    continue
except ccxt.ExchangeError as e:
    print(f"Exchange error: {e}")
    time.sleep(600)  # Wait 10 minutes
    continue
```

### Performance Issues

#### ❌ Slow Query Performance
**Symptoms:**
- Grafana dashboards load slowly
- Database queries timeout
- High CPU usage

**Solutions:**
```sql
-- Update table statistics
ANALYZE ohlcv_1m;
ANALYZE ohlcv_5m;

-- Check for missing indexes
SELECT * FROM pg_stat_user_tables WHERE relname IN ('ohlcv_1m', 'ohlcv_5m');

-- Check slow queries
SELECT query, mean_time, calls 
FROM pg_stat_statements 
WHERE query LIKE '%ohlcv%'
ORDER BY mean_time DESC;
```

#### ❌ High Memory Usage
**Symptoms:**
- System becomes unresponsive
- Docker containers killed by OOM
- Swap usage high

**Solutions:**
```bash
# Limit container memory in docker-compose.yml
services:
  db:
    mem_limit: 2g
    memswap_limit: 2g

# Tune PostgreSQL memory settings
# Add to docker-compose.yml environment:
- POSTGRES_SHARED_BUFFERS=256MB
- POSTGRES_EFFECTIVE_CACHE_SIZE=1GB
- POSTGRES_WORK_MEM=4MB
```

## 🔧 Debugging Commands

### System Information
```bash
# Check system resources
free -h
df -h
docker system df

# Check Docker status
docker version
docker compose version
systemctl status docker
```

### Container Debugging
```bash
# View all container logs
docker compose logs --tail=50

# Follow logs in real-time
docker compose logs -f

# Execute commands in containers
docker exec -it tsdb bash
docker exec -it grafana bash

# Check container resource usage
docker stats --no-stream
```

### Database Debugging
```bash
# Check database size
docker exec tsdb psql -U trader -d market -c "
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(tablename::text)) as size
FROM pg_tables 
WHERE schemaname = 'public';"

# Check active connections
docker exec tsdb psql -U trader -d market -c "
SELECT pid, usename, application_name, client_addr, state, query_start 
FROM pg_stat_activity 
WHERE datname = 'market';"

# Check locks
docker exec tsdb psql -U trader -d market -c "
SELECT * FROM pg_locks l 
JOIN pg_stat_activity a ON l.pid = a.pid 
WHERE NOT granted;"
```

## 📞 Getting Help

### Log Collection
Before asking for help, collect these logs:

```bash
# Create debug info bundle
mkdir debug-info
docker compose logs > debug-info/docker-logs.txt
docker compose ps > debug-info/container-status.txt
docker system df > debug-info/docker-disk.txt
cp .env debug-info/env-vars.txt
docker exec tsdb psql -U trader -d market -c "\dt+" > debug-info/database-tables.txt

# Compress for sharing
tar -czf debug-info.tar.gz debug-info/
```

### Support Channels
- **GitHub Issues**: https://github.com/your-username/alphadb/issues
- **Discussions**: Community questions and help
- **Discord**: Real-time chat support

### What to Include in Bug Reports
1. **Environment**: OS, Docker version, available RAM/disk
2. **Steps to reproduce**: Exact commands that cause the issue
3. **Expected behavior**: What should happen
4. **Actual behavior**: What actually happens
5. **Logs**: Relevant container logs and error messages
6. **Configuration**: Your .env file (with passwords redacted)

---

**Need more help?** Check our [GitHub Issues](https://github.com/your-username/alphadb/issues) or start a [Discussion](https://github.com/your-username/alphadb/discussions).