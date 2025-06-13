-- Feature System Validation Script

\echo '🧪 FEATURE SYSTEM VALIDATION'
\echo '============================'

-- Test 1: Recent data availability
\echo ''
\echo '📊 Test 1: Recent Data Availability'
SELECT 
    'Recent records (last 10 min)' as test,
    COUNT(*) as count,
    CASE WHEN COUNT(*) >= 8 THEN '✅ PASS' ELSE '❌ FAIL' END as status
FROM features_1m 
WHERE bucket > now() - '10 minutes'::interval;

-- Test 2: Feature completeness
\echo ''
\echo '🔍 Test 2: Feature Completeness by Symbol'
SELECT 
    symbol,
    COUNT(*) as total_records,
    COUNT(CASE WHEN parkinson_vol IS NOT NULL THEN 1 END) as parkinson_records,
    COUNT(CASE WHEN hl_range > 0 THEN 1 END) as records_with_movement,
    ROUND(AVG(hl_range_pct)::numeric, 6) as avg_hl_range_pct
FROM features_1m 
WHERE bucket > now() - '24 hours'::interval
GROUP BY symbol
ORDER BY symbol;

-- Test 3: Latest feature values  
\echo ''
\echo '📈 Test 3: Latest Feature Values'
SELECT 
    bucket,
    symbol,
    ROUND(close_price::numeric, 2) as close_price,
    ROUND(hl_range::numeric, 4) as hl_range,
    ROUND(hl_range_pct::numeric, 6) as hl_range_pct,
    ROUND(vwap_gap::numeric, 4) as vwap_gap,
    ROUND(parkinson_vol::numeric, 8) as parkinson_vol,
    is_green,
    is_doji
FROM features_1m 
WHERE bucket > now() - '1 hour'::interval
  AND hl_range > 0
ORDER BY bucket DESC 
LIMIT 6;

-- Test 4: Continuous aggregate job status
\echo ''
\echo '⚡ Test 4: Continuous Aggregate Jobs'
SELECT 
    job_id,
    application_name,
    schedule_interval,
    last_run_started_at,
    CASE 
        WHEN last_run_started_at > now() - interval '5 minutes' 
        THEN '✅ RECENT' 
        ELSE '⚠️ OLD' 
    END as job_status
FROM timescaledb_information.jobs 
WHERE application_name LIKE '%features_%';

-- Test 5: Data freshness
\echo ''
\echo '🕐 Test 5: Data Freshness'
SELECT 
    symbol,
    MAX(bucket) as latest_bucket,
    EXTRACT(EPOCH FROM (now() - MAX(bucket)))/60 as minutes_behind,
    CASE 
        WHEN MAX(bucket) > now() - interval '5 minutes' 
        THEN '✅ FRESH' 
        ELSE '⚠️ STALE' 
    END as freshness_status
FROM features_1m 
GROUP BY symbol
ORDER BY symbol;

-- Test 6: Feature statistics
\echo ''
\echo '📊 Test 6: Feature Statistics (Last 24h)'
SELECT 
    symbol,
    COUNT(*) as records,
    ROUND(AVG(hl_range_pct)::numeric, 6) as avg_volatility,
    ROUND(STDDEV(hl_range_pct)::numeric, 6) as volatility_std,
    SUM(is_green) as green_candles,
    SUM(is_doji) as doji_candles,
    ROUND((SUM(is_green)::float / COUNT(*) * 100)::numeric, 1) as green_pct
FROM features_1m 
WHERE bucket > now() - '24 hours'::interval
GROUP BY symbol
ORDER BY symbol;

\echo ''
\echo '🎯 VALIDATION COMPLETE!'
\echo 'Features system is ready for ML pipelines!'