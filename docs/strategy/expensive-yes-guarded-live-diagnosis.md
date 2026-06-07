# Expensive YES Guarded Live Run Diagnosis

## Current Status / Risk Action

- No live code, runtime config, schedule, or order authority is changed by this diagnosis.
- The proposed strategy is a separate `expensive_yes_live` strategy id, not a change to `fair_value_live`.
- The intended first use is paper or gated live with explicit live submission still controlled by existing runtime flags, live run locks, and live risk admission state.

## Observed Opportunity

- The KXBTC15M due-diligence notebook found an `expensive_yes` bucket worth investigating: YES asks at or above about `0.65` showed positive one-day replay PnL.
- The top bucket was roughly `+6.08%` net ROI and `+3.73%` stress ROI on the inspected public slice, with realized frequency above average implied ask.
- The evidence is not strong enough to treat the bucket as a proven strategy because it is a narrow public-data slice, dominated by one day, and based on candle/replay evidence rather than executable fills.

## Evidence Inspected

- Notebook output opened from `kxbtc15m_due_diligence.html`.
- Public Kalshi KXBTC15M one-day slice around June 5, 2026.
- PnL attribution summary, top-finding drilldown, broad baselines, final-window baseline, and concentration flags.
- Existing fair-value live runtime docs and code paths for dashboard-owned config, run status, live risk admission state, taker-only IOC orders, and live run lock behavior.

## Missing Or Weak Evidence

- No 7d, 30d, or 60d persistence check yet.
- No exchange fillability audit for this rule.
- No live latency/slippage measurement specific to expensive YES entries.
- No independent proof that the one-day result survives capacity, quote staleness, spread stress, or regime changes.

## Suspected Failure Modes

- **Selection illusion**: the one-day bucket may be dominated by a transient market regime.
- **Execution damage**: public candles may overstate executable fills at the observed asks.
- **Concentration**: PnL may come from too few markets or one trading day.
- **Sizing risk**: even small orders can create repeated near-$1 max-loss exposure if the rule fires often.
- **Data-quality drift**: market discovery, quote freshness, or settlement labels could differ between notebook replay and live runtime.

## One Next Experiment

Run a guarded MVP probe using `expensive_yes_live`:

- Scan current KXBTC15M markets using the existing live acquisition path.
- Buy or paper-buy YES only when executable YES ask is at or above the configured threshold, default `0.65`.
- Default to one contract-equivalent per eligible market through `$1` max order and `$1` per-market exposure caps.
- Keep a small daily loss cap, default `$10`, and a small market scan cap.
- Record every trade or skip with quote freshness, selected ask, threshold, sizing config, risk result, order response, fills, and eventual settlement.

## Proposed Code / Config Changes

- Recommended: create a tightly scoped PRD for `expensive_yes_live`.
- Reuse fair-value live runtime infrastructure where practical: dashboard-owned runtime config, live run lock, status materialization, risk admission state, taker-only IOC order client, and performance payload patterns.
- Avoid new guardrail architecture, maker execution, model work, or broad research artifact work in the MVP.
