#!/bin/bash

# Historical Data Backfill Runner
# Fetches 90 days of OHLCV data for feature engineering

echo "🚀 Starting Historical Data Backfill..."
echo "This will fetch 90 days of BTC and ETH data from Kraken"
echo "Estimated time: 10-15 minutes"
echo

# Check if database is running
if ! docker exec tsdb pg_isready -U trader > /dev/null 2>&1; then
    echo "❌ Database not accessible. Make sure TimescaleDB container is running."
    exit 1
fi

echo "✅ Database connection verified"

# Set environment variables for the script
export POSTGRES_USER=${POSTGRES_USER:-trader}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-s3cr3t}
export POSTGRES_DB=${POSTGRES_DB:-market}
export DB_HOST=${DB_HOST:-localhost}
export DB_PORT=${DB_PORT:-5432}

echo "📊 Starting backfill process..."
echo "   - Symbols: BTC/USDT, ETH/USDT"
echo "   - Period: 90 days"
echo "   - Frequency: 1-minute bars"
echo "   - Expected: ~129,600 bars per symbol"
echo

# Run the backfill script
python3 scripts/backfill.py

if [ $? -eq 0 ]; then
    echo
    echo "✅ Backfill completed successfully!"
    echo
    echo "📊 Data Summary:"
    docker exec tsdb psql -U trader -d market -c "
        SELECT 
            'BTC/USDT' as symbol,
            COUNT(*) as bars,
            MIN(ts) as earliest,
            MAX(ts) as latest
        FROM ohlcv_btc_usdt
        UNION ALL
        SELECT 
            'ETH/USDT' as symbol,
            COUNT(*) as bars,
            MIN(ts) as earliest,
            MAX(ts) as latest
        FROM ohlcv_eth_usdt
        ORDER BY symbol;
    "
    echo
    echo "🎯 Your data is now ready for feature engineering!"
    echo "   - Use tables: ohlcv_btc_usdt, ohlcv_eth_usdt"
    echo "   - 5-minute aggregates: ohlcv_btc_usdt_5m, ohlcv_eth_usdt_5m"
else
    echo "❌ Backfill failed. Check the logs above for details."
    exit 1
fi