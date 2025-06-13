#!/bin/bash

# CoinGecko Historical Data Backfill Runner
# Fetches 90 days of OHLCV data for feature engineering using CoinGecko Pro API

echo "🚀 Starting CoinGecko Historical Data Backfill..."
echo "This will fetch 90 days of 1-minute BTC and ETH data from CoinGecko Pro API"
echo "Estimated time: 3-5 minutes"
echo

# Check if CoinGecko API key is set
if [ -z "$COINGECKO_API_KEY" ]; then
    echo "❌ COINGECKO_API_KEY environment variable not set"
    echo "Please set your CoinGecko Pro API key:"
    echo "export COINGECKO_API_KEY=your_api_key_here"
    exit 1
fi

echo "✅ CoinGecko API key found"

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

echo "📊 Starting CoinGecko backfill process..."
echo "   - Symbols: BTC/USDT, ETH/USDT"
echo "   - Period: 90 days"
echo "   - Frequency: 1-minute OHLCV bars"
echo "   - Source: CoinGecko Pro API"
echo "   - Expected: ~129,600 bars per symbol"
echo

# Install requests if not available
python3 -c "import requests" 2>/dev/null || {
    echo "Installing requests library..."
    pip3 install requests
}

# Run the CoinGecko backfill script
cd "$(dirname "$0")"  # Change to scripts directory
python3 coingecko_backfill.py

if [ $? -eq 0 ]; then
    echo
    echo "✅ CoinGecko backfill completed successfully!"
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
    echo "🎯 Your 90-day historical dataset is now ready for feature engineering!"
    echo "   - Use tables: ohlcv_btc_usdt, ohlcv_eth_usdt"
    echo "   - 5-minute aggregates: ohlcv_btc_usdt_5m, ohlcv_eth_usdt_5m"
    echo "   - Data quality: 1-minute OHLCV with volume from CoinGecko Pro"
    echo
    echo "💡 Next steps:"
    echo "   - Run technical analysis on the historical data"
    echo "   - Create additional time-based aggregates (hourly, 4h, daily)"
    echo "   - Implement feature engineering pipelines"
else
    echo "❌ CoinGecko backfill failed. Check the logs above for details."
    exit 1
fi