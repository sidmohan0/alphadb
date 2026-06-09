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
as `manifest.json`, `decision_rows.json`, `live_order_attempts.json`, and
`live_reconciliation_report.json`. The tool reads only local files; it does not
connect to production Postgres, require exchange credentials, submit orders,
write operational state, or change runtime behavior.

The CSV normalizes one row per candidate/order attempt where fields are
available: decision and quote timestamps, quote age, active-context age,
Coinbase diagnostic age, intended side and price, edge, min edge, diagnostic
class, fresh-quote counterfactual status, risk admission status, submit timing,
fill counts, compact PnL, and hot-path phase timings.

The Markdown report includes data coverage, hot-path p50/p95/max timing,
quote-age buckets, active-context-age buckets, hot-path latency buckets,
fill-rate summaries, side/price/edge buckets, diagnostic-class summaries,
skip/reject/error reasons, adverse-selection checks, fresh-quote
counterfactual status, implementation-drag status, and a bottleneck verdict from
the accepted MVP verdict set.

Implementation-drag dollars are intentionally conservative. If the artifacts do
not already provide edge-at-submit, fresh-quote counterfactuals, or
`counterfactual_pnl_if_available`, the report says `unavailable` instead of
fabricating money-left-on-table estimates. Exchange responses are not treated as
fresh-quote counterfactual evidence.

Active-context freshness is source-aware. `brti_primary` rows use BRTI latest
context age and status; Coinbase fields remain diagnostic only. `coinbase_primary`
rows use Coinbase feature freshness. `fixture` rows mark active-context
freshness as not applicable/non-blocking.

Public-safe synthetic coverage lives under
`tests/fixtures/execution_attribution/live_runs/`.
