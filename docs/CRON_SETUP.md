# Daily Backfill Cron Setup Guide 🕐

Automated daily backfills ensure your AlphaDB never has data gaps, even if the real-time feeds experience downtime.

## 🎯 Overview

The daily backfill system:
- ✅ **Runs at 2:00 AM daily** to catch any gaps from the previous day
- ✅ **Uses CoinGecko Pro API** for reliable data with good rate limits
- ✅ **Logs everything** for monitoring and debugging
- ✅ **Only backfills 2 days** to minimize API usage while ensuring coverage
- ✅ **Automatically handles errors** and provides status reporting

## 🚀 Quick Setup

### 1. One-Command Setup
```bash
./scripts/setup_cron.sh
```

This script will:
- Check if the daily backfill script exists
- Show your current crontab
- Add the daily backfill job
- Confirm the setup

### 2. Manual Setup (Alternative)

If you prefer to set it up manually:

```bash
# Edit your crontab
crontab -e

# Add this line (replace /path/to with your actual path):
0 2 * * * /Users/sidmohan/Projects/alphadb/scripts/daily_backfill_cron.sh
```

## 📋 Cron Schedule Details

| Field | Value | Description |
|-------|-------|-------------|
| Minute | 0 | Run at minute 0 |
| Hour | 2 | Run at 2:00 AM |
| Day of Month | * | Every day |
| Month | * | Every month |
| Day of Week | * | Every day of week |

**Translation**: `0 2 * * *` = "Every day at 2:00 AM"

## 📊 What Gets Backfilled

The daily cron job:

1. **Checks Environment**
   - Verifies CoinGecko API key is set
   - Confirms AlphaDB database is accessible

2. **Runs Incremental Backfill**
   - Fetches last 2 days of data for BTC/USDT and ETH/USDT
   - Updates existing records and fills any gaps
   - Uses the same CoinGecko script as manual backfills

3. **Logs Everything**
   - All output goes to `/var/log/alphadb-backfill.log`
   - Includes timestamps and status indicators
   - Reports data quality statistics

## 📝 Monitoring Your Backfills

### View Recent Logs
```bash
# See the last 20 lines
tail -20 /var/log/alphadb-backfill.log

# Follow logs in real-time
tail -f /var/log/alphadb-backfill.log

# Search for errors
grep "ERROR\\|❌" /var/log/alphadb-backfill.log
```

### Check Cron Status
```bash
# List current cron jobs
crontab -l

# Check if cron service is running (Linux)
systemctl status cron

# Check if cron service is running (macOS)
sudo launchctl list | grep cron
```

### Data Quality Check
```bash
# Connect to database and check recent data
docker exec -it tsdb psql -U trader -d market

# Check data freshness
SELECT 'BTC' as symbol, COUNT(*) as records, MAX(ts) as latest FROM ohlcv_btc_usdt
UNION ALL
SELECT 'ETH' as symbol, COUNT(*) as records, MAX(ts) as latest FROM ohlcv_eth_usdt;
```

## ⚙️ Configuration

### Environment Variables

The cron job reads from your `.env` file:

```bash
# Required for CoinGecko API
COINGECKO_API_KEY=your_api_key_here

# Database connection (defaults shown)
POSTGRES_USER=trader
POSTGRES_PASSWORD=s3cr3t
POSTGRES_DB=market
```

### Customizing the Schedule

Common cron schedule variations:

```bash
# Every 6 hours
0 */6 * * * /path/to/daily_backfill_cron.sh

# Twice daily (6 AM and 6 PM)
0 6,18 * * * /path/to/daily_backfill_cron.sh

# Weekdays only at 3 AM
0 3 * * 1-5 /path/to/daily_backfill_cron.sh

# Every hour (for high-frequency needs)
0 * * * * /path/to/daily_backfill_cron.sh
```

### Customizing Backfill Period

Edit `scripts/daily_backfill_cron.sh` to change the backfill period:

```bash
# Current: backfill last 2 days
backfiller.run_backfill(days=2)

# Alternative: backfill last 7 days (more conservative)
backfiller.run_backfill(days=7)

# Alternative: backfill last 1 day (minimal)
backfiller.run_backfill(days=1)
```

## 🔧 Troubleshooting

### Cron Job Not Running

1. **Check if cron service is running**:
   ```bash
   # Linux
   sudo systemctl status cron
   
   # macOS
   sudo launchctl list | grep cron
   ```

2. **Verify crontab entry**:
   ```bash
   crontab -l | grep alphadb
   ```

3. **Test script manually**:
   ```bash
   /Users/sidmohan/Projects/alphadb/scripts/daily_backfill_cron.sh
   ```

### Permission Issues

1. **Make scripts executable**:
   ```bash
   chmod +x /Users/sidmohan/Projects/alphadb/scripts/daily_backfill_cron.sh
   chmod +x /Users/sidmohan/Projects/alphadb/scripts/coingecko_backfill.py
   ```

2. **Check log file permissions**:
   ```bash
   sudo mkdir -p /var/log
   sudo touch /var/log/alphadb-backfill.log
   sudo chown $USER:$USER /var/log/alphadb-backfill.log
   ```

### API Key Issues

1. **Verify API key is set**:
   ```bash
   echo $COINGECKO_API_KEY
   ```

2. **Test API key manually**:
   ```bash
   curl -H "X-Cg-Pro-Api-Key: $COINGECKO_API_KEY" \
     "https://pro-api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
   ```

### Database Connection Issues

1. **Check if AlphaDB stack is running**:
   ```bash
   docker ps | grep tsdb
   ```

2. **Test database connection**:
   ```bash
   docker exec tsdb pg_isready -U trader
   ```

## 📈 Log Analysis

### Sample Log Entries

**Successful Run**:
```
[2025-06-13 02:00:01] 🕐 Starting daily backfill cron job
[2025-06-13 02:00:01] ✅ Environment check passed
[2025-06-13 02:00:01] 📊 Running incremental backfill for last 2 days...
[2025-06-13 02:00:45] ✅ Daily backfill completed successfully
[2025-06-13 02:00:46] 🔍 Running data quality check...
[2025-06-13 02:00:47] 📊 Data quality check complete
[2025-06-13 02:00:47] 🏁 Daily backfill cron job completed
```

**Failed Run**:
```
[2025-06-13 02:00:01] 🕐 Starting daily backfill cron job
[2025-06-13 02:00:01] ❌ Database not accessible. Is AlphaDB stack running?
```

### Log Rotation

To prevent log files from growing too large:

```bash
# Add to /etc/logrotate.d/alphadb-backfill
/var/log/alphadb-backfill.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    create 644 $USER $USER
}
```

## 🔔 Alerting (Optional)

### Slack Integration

Add to `daily_backfill_cron.sh` for failure notifications:

```bash
# Add at the end of the script
if [ $BACKFILL_STATUS -ne 0 ]; then
    curl -X POST -H 'Content-type: application/json' \
      --data '{"text":"🚨 AlphaDB daily backfill failed at $(date)"}' \
      $SLACK_WEBHOOK_URL
fi
```

### Email Notifications

Set up email notifications via cron:

```bash
# Add MAILTO to crontab
MAILTO=your-email@example.com
0 2 * * * /path/to/daily_backfill_cron.sh
```

## ✅ Verification Checklist

After setup, verify everything is working:

- [ ] Cron job is listed in `crontab -l`
- [ ] Script is executable (`ls -la scripts/daily_backfill_cron.sh`)
- [ ] Environment variables are accessible to cron
- [ ] Log file is being created (`/var/log/alphadb-backfill.log`)
- [ ] Manual script execution works
- [ ] Database connection works from cron environment
- [ ] CoinGecko API key is valid and accessible

## 🎯 Best Practices

1. **Monitor Regularly**: Check logs weekly to ensure backfills are running
2. **Test Changes**: Always test cron jobs manually before deploying
3. **Log Rotation**: Set up log rotation to prevent disk space issues
4. **API Limits**: Monitor your CoinGecko API usage to stay within limits
5. **Backup Strategy**: Keep database backups independent of the live system
6. **Documentation**: Update this guide when you make changes

---

## 📚 Additional Resources

- [Cron Expression Generator](https://crontab.guru/)
- [CoinGecko Pro API Documentation](https://docs.coingecko.com/v3.0.1/reference/introduction)
- [TimescaleDB Continuous Aggregates](https://docs.timescale.com/timescaledb/latest/how-to-guides/continuous-aggregates/)

Your AlphaDB now has bulletproof data continuity! 🛡️