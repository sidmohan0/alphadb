# Live Runtime Latency And Edge Attribution

## Status

ALP-269 evidence contract. Implemented by ALP-279 through ALP-283.

## Problem

Fair-value live runs need enough evidence to explain whether `edge_below_min`
means the candidate truly lacked edge at decision time or whether quote/context
freshness and runtime timing made the evidence latency-suspect. The answer must
be observable after the run without changing live behavior.

## Non-Goals

- No live decision changes.
- No order timing, submission behavior, risk cap, or `min_edge` changes.
- No new Operational State table.
- No new dashboard view, chart, drilldown, or control.
- No second hot-path quote read.
- No fresh-quote counterfactual inferred from exchange responses.

## Evidence Contract

Live edge attribution is read-only diagnostic evidence. It decomposes the
decision-time selected side into fair value, executable quote, taker fee, edge,
configured edge hurdle, edge shortfall/margin, quote freshness, active
market-context freshness, compact hot-path timing, diagnostic class, and
fresh-quote counterfactual availability.

Active-context freshness follows `market_context_source`:

- `brti_primary`: BRTI latest context age/status is the active context. Coinbase
  remains diagnostic-only and must not make a fresh-BRTI decision context-stale.
- `coinbase_primary`: Coinbase feature age/status is the active context.
- `fixture`: active-context freshness is not applicable and non-blocking.

Fresh-quote counterfactuals are explicit. Unless artifacts contain independent
fresh quote evidence at or after submit time, attribution records
`fresh_quote_counterfactual.status = unavailable`. Reports must not estimate
missed PnL or implementation-drag dollars from exchange responses alone.

## Artifact And Surface Split

Detailed candidate attribution is artifact-first. `decision_rows.json` may carry
`live_edge_attribution` for every fair-value decision row that reached
fair-value decisioning. Missing fields produce partial attribution instead of
failing the run.

Compact operator surfacing remains selected/latest only:

- `manifest.json` keeps the selected/latest `live_edge_attribution`.
- `live_order_attempts.json` keeps attempt-level attribution for the selected
  submitted/skipped attempt.
- `live_run_statuses`, Performance summaries, and dashboard payloads continue to
  expose compact selected/latest attribution and recent attribution buckets.

Execution attribution reports may group artifact evidence by quote-age bucket,
active-context-age bucket, hot-path timing bucket, edge bucket, reason, and
diagnostic class. These buckets are report-only thresholds, not runtime knobs.

## Child Issue Boundaries

- ALP-279: active-source-aware live edge attribution and unavailable
  fresh-quote counterfactual status.
- ALP-280: candidate-level attribution in fair-value artifacts while preserving
  selected/latest manifest and live-order-attempt attribution.
- ALP-281: report-only latency/freshness/edge/reason/diagnostic buckets.
- ALP-282: preserve compact status, performance, and dashboard surfacing without
  adding a new UI surface.
- ALP-283: document this final evidence contract.
