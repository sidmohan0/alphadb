#!/bin/sh
set -eu

node /app/apps/api/dist/markets/maintenance/marketStateSchema.js
node /app/apps/api/dist/polymarket/maintenance/migrateDiscoveryRuns.js
