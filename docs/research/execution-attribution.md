# Execution Attribution MVP

This read-only research path turns copied fair-value live run artifacts into:

- `execution_attribution.csv`
- `execution_attribution_report.md`

Run it against a local live-run artifact root or copied postmortem directory:

```bash
alphadb-model-eval execution-attribution \
  --input artifacts/fair-value-live \
  --output-dir artifacts/execution-attribution
```

The input should contain one or more run directories with compact MVP files such
as `manifest.json`, `live_order_attempts.json`, and
`live_reconciliation_report.json`. The tool reads only local files; it does not
connect to production Postgres, require exchange credentials, submit orders,
write operational state, or change runtime behavior.

The CSV normalizes one row per candidate/order attempt where fields are
available: decision and quote timestamps, quote/Coinbase age, intended side and
price, edge, risk admission status, submit timing, fill counts, compact PnL, and
hot-path phase timings.

The Markdown report includes data coverage, hot-path p50/p95/max timing,
freshness buckets, fill-rate summaries, side/price/edge buckets,
skip/reject/error reasons, adverse-selection checks, implementation-drag status,
and a bottleneck verdict from the accepted MVP verdict set.

Implementation-drag dollars are intentionally conservative. If the artifacts do
not already provide edge-at-submit, fresh-quote counterfactuals, or
`counterfactual_pnl_if_available`, the report says `insufficient_data` instead
of fabricating money-left-on-table estimates.

Public-safe synthetic coverage lives under
`tests/fixtures/execution_attribution/live_runs/`.
