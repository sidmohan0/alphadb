#!/bin/bash

# Setup Cron Job for Daily Backfill
# Run this script once to install the daily backfill cron job

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_SCRIPT="$SCRIPT_DIR/daily_backfill_cron.sh"

echo "🕐 Setting up daily backfill cron job for AlphaDB"
echo

# Check if script exists and is executable
if [ ! -x "$CRON_SCRIPT" ]; then
    echo "❌ Daily backfill script not found or not executable: $CRON_SCRIPT"
    exit 1
fi

echo "✅ Found daily backfill script: $CRON_SCRIPT"

# Show current crontab
echo "📋 Current crontab entries:"
crontab -l 2>/dev/null || echo "No crontab entries found"
echo

# Create cron entry
CRON_ENTRY="0 2 * * * $CRON_SCRIPT"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "$CRON_SCRIPT"; then
    echo "⚠️  Cron job already exists for this script"
    echo "Current entry:"
    crontab -l | grep "$CRON_SCRIPT"
    echo
    read -p "Do you want to replace it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled. No changes made."
        exit 0
    fi
    
    # Remove existing entry
    (crontab -l 2>/dev/null | grep -v "$CRON_SCRIPT") | crontab -
    echo "🗑️  Removed existing cron entry"
fi

# Add new cron entry
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo "✅ Added cron job:"
echo "   $CRON_ENTRY"
echo
echo "📋 Updated crontab:"
crontab -l
echo

echo "🎯 Cron job configuration:"
echo "   - Runs daily at 2:00 AM"
echo "   - Backfills last 2 days to catch gaps"
echo "   - Uses CoinGecko Pro API"
echo "   - Logs to /var/log/alphadb-backfill.log"
echo

echo "💡 Tips:"
echo "   - Monitor logs: tail -f /var/log/alphadb-backfill.log"
echo "   - Remove cron job: crontab -e (then delete the line)"
echo "   - Test manually: $CRON_SCRIPT"
echo

echo "✅ Daily backfill cron job setup complete!"