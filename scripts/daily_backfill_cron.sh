#!/bin/bash

# Daily Backfill Cron Job for AlphaDB
# Runs daily to fill any gaps in data using CoinGecko Pro API
# Add to crontab: 0 2 * * * /path/to/daily_backfill_cron.sh

# Set script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment variables from .env file
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
fi

# Log file for cron output
LOG_FILE="/var/log/alphadb-backfill.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "🕐 Starting daily backfill cron job"

# Check if CoinGecko API key is set
if [ -z "$COINGECKO_API_KEY" ]; then
    log "❌ COINGECKO_API_KEY not set. Skipping backfill."
    exit 1
fi

# Check if database is accessible
if ! docker exec tsdb pg_isready -U trader > /dev/null 2>&1; then
    log "❌ Database not accessible. Is AlphaDB stack running?"
    exit 1
fi

log "✅ Environment check passed"

# Change to script directory
cd "$SCRIPT_DIR"

# Run incremental backfill (last 2 days to catch any gaps)
log "📊 Running incremental backfill for last 2 days..."

# Create temporary backfill script for shorter period
cat > temp_daily_backfill.py << 'EOF'
#!/usr/bin/env python3
"""
Daily incremental backfill - fills last 2 days to catch any gaps
"""
import sys
import os

# Add the scripts directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coingecko_backfill import CoinGeckoBackfill
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Run daily incremental backfill"""
    try:
        # Only backfill last 2 days to catch gaps
        backfiller = CoinGeckoBackfill()
        backfiller.run_backfill(days=2)
        
        logger.info("✅ Daily backfill completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"❌ Daily backfill failed: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
EOF

# Run the incremental backfill
python3 temp_daily_backfill.py >> "$LOG_FILE" 2>&1
BACKFILL_STATUS=$?

# Clean up temporary file
rm -f temp_daily_backfill.py

if [ $BACKFILL_STATUS -eq 0 ]; then
    log "✅ Daily backfill completed successfully"
    
    # Optional: Run data quality check
    log "🔍 Running data quality check..."
    
    docker exec tsdb psql -U trader -d market -c "
        SELECT 
            'Data Quality Report' as report,
            'BTC/USDT' as symbol,
            COUNT(*) as total_records,
            MIN(ts) as earliest,
            MAX(ts) as latest
        FROM ohlcv_btc_usdt
        UNION ALL
        SELECT 
            'Data Quality Report' as report,
            'ETH/USDT' as symbol,
            COUNT(*) as total_records,
            MIN(ts) as earliest,
            MAX(ts) as latest
        FROM ohlcv_eth_usdt;
    " >> "$LOG_FILE" 2>&1
    
    log "📊 Data quality check complete"
    
else
    log "❌ Daily backfill failed with status: $BACKFILL_STATUS"
    
    # Optional: Send alert (email, Slack, etc.)
    # Example: curl -X POST -H 'Content-type: application/json' \
    #   --data '{"text":"AlphaDB daily backfill failed"}' \
    #   $SLACK_WEBHOOK_URL
fi

log "🏁 Daily backfill cron job completed"

exit $BACKFILL_STATUS