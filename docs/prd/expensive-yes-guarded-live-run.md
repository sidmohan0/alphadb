# Expensive YES Guarded Live Run PRD

## Problem Statement

The KXBTC15M due-diligence notebook surfaced a possible trading pocket: expensive YES contracts, defined as executable YES asks at or above about `0.65`, looked profitable on a narrow public-data replay. The result is interesting but not strategy-quality proof. It is single-slice evidence, dominated by limited history, and does not prove executable fills.

For the MVP, the operator does not want a large architecture refactor or a new guardrail system. The immediate product need is simpler: test whether this bucket is actually tradable in live conditions with tiny size, clear dashboard-owned config, and the same runtime safety plumbing already used by the fair-value strategy.

## Solution

Add an **Expensive YES guarded live run** as a separate strategy id: `expensive_yes_live`.

The strategy scans live KXBTC15M markets, considers only YES, and creates at most one small taker-only IOC attempt per eligible market when the executable YES ask is at or above the configured threshold. The default threshold is `0.65`. Default sizing is intentionally tiny: one contract-equivalent per market, a small daily loss cap, and no maker behavior.

The implementation should reuse the fair-value live runtime components wherever practical: dashboard-owned runtime config storage, live run lock, quote freshness checks, live risk admission state, taker-only IOC order client, compact manifests, status materialization, and performance/status surfaces. Dashboard config must let the operator modify the sizing opinions and threshold for `expensive_yes_live` without redeploying.

## User Stories

1. As the operator, I want `expensive_yes_live` to be separate from `fair_value_live`, so that config, status, and performance do not mix two different strategies.
2. As the operator, I want to see and edit the expensive YES config from the dashboard, so that I can change the threshold and size without redeploying.
3. As the operator, I want the default YES ask threshold to be `0.65`, so that the live rule matches the notebook finding.
4. As the operator, I want the threshold shown in strategy language as "YES ask threshold", so that `min_contract_price` is not confusing in this context.
5. As the operator, I want the default order size to be one contract-equivalent, so that the first run measures executable reality without meaningful capital risk.
6. As the operator, I want a per-market exposure cap, so that repeated runs cannot build more than the intended position in one market.
7. As the operator, I want a small daily loss cap, so that a bad day stops quickly.
8. As the operator, I want a market scan cap, so that the job remains bounded and predictable.
9. As the operator, I want live submission to remain behind the existing explicit live-order controls, so that deploying the strategy does not automatically trade.
10. As the operator, I want paper mode to use the same decision rule and config, so that I can inspect behavior before allowing live orders.
11. As the operator, I want every eligible market to produce a trade or skip record, so that I can audit why the strategy did or did not act.
12. As the operator, I want skip reasons for below-threshold asks, stale quotes, missing risk state, market exposure cap, daily cap, lock contention, and live disabled, so that failures are explainable.
13. As the operator, I want each order attempt to record observed YES ask, threshold, intended contracts, sized contracts, max loss, risk admission result, and exchange response, so that execution quality is inspectable.
14. As the operator, I want no maker orders in this MVP, so that fill analysis stays simple and risk is bounded.
15. As the operator, I want the strategy to reuse existing live risk admission state, so that we do not invent another risk path.
16. As the operator, I want no new approval maze, RBAC, or enterprise safety workflow, so that MVP speed is preserved.
17. As the operator, I want compact performance for this strategy, so that I can compare filled, skipped, rejected, and settled outcomes.
18. As the operator, I want the dashboard to make clear which strategy config I am editing, so that fair-value settings are not accidentally changed.
19. As a researcher, I want the live probe to preserve quote and fill evidence, so that we can decide whether expensive YES deserves longer-window research.
20. As a researcher, I want the run output to expose concentration and capacity warnings later, so that early PnL is not mistaken for proof.
21. As an engineer, I want the implementation to reuse fair-value live components, so that this ships as one additional strategy rather than a platform rewrite.
22. As an engineer, I want strategy-specific code to be small and testable, so that the expensive YES rule can be verified without mocking the whole runtime.
23. As an engineer, I want the existing config repository keyed by strategy to be used, so that config history and active config behavior remain consistent.
24. As an engineer, I want status and performance queries to accept a strategy id, so that the dashboard can show fair-value and expensive-YES independently.
25. As a future maintainer, I want this PRD to state what the probe does not prove, so that a successful microprobe is not confused with model promotion or target-platform cutover.

## Acceptance Criteria

- A separate `expensive_yes_live` strategy id exists and does not share active config, status, risk admission state, or performance summaries with `fair_value_live`.
- The expensive YES rule buys or paper-buys only YES contracts whose executable ask is greater than or equal to the configured threshold.
- Default threshold is `0.65`.
- Default sizing is one contract-equivalent per eligible market, with small configurable per-order, per-market, daily loss, and market scan caps.
- Dashboard config supports editing the expensive YES runtime config separately from fair-value config.
- The dashboard labels the threshold in strategy-specific language while preserving the existing storage shape where practical.
- The runtime records trade and skip outcomes with enough evidence to interpret quote freshness, threshold pass/fail, sizing, risk admission, order submission, fill/no-fill, and settlement outcome.
- Live order submission remains controlled by existing live-order flags, runtime guard, live run lock, and live risk admission state.
- The implementation does not add maker execution, new guardrail architecture, new auth/RBAC, model promotion, or target-platform cutover.
- Existing fair-value live behavior remains unchanged.

## Implementation Decisions

- Build `expensive_yes_live` as one additional live strategy, not as a fair-value mode.
- Reuse the existing dashboard-owned runtime config repository because it is already keyed by `strategy`.
- Use the existing `min_contract_price` persisted field as the expensive YES threshold where practical. In UI/API copy for this strategy, present it as "YES ask threshold".
- Seed `expensive_yes_live` with defaults oriented around the microprobe: approximately `$1` max order, `$1` per-market exposure, `$10` daily loss cap, `0.65` threshold, and a small market scan cap.
- Keep `min_edge` present only if required by shared config shape. The expensive YES decision rule does not need fair-value edge.
- Add strategy selection to dashboard config/status/performance surfaces rather than hardcoding `fair_value_live`.
- Keep the first dashboard UI small: strategy selector or second strategy config section is enough.
- Implement the decision rule as a small testable module or function that turns market quote state plus runtime config into trade or skip decisions.
- Reuse existing market acquisition, quote freshness, live run lock, live risk admission, IOC order request, order submission, manifest, and status materialization patterns from fair-value live.
- Preserve taker-only execution. Do not add maker/post-only behavior.
- Ensure paper and live modes use the same rule and config snapshot.
- Record a config snapshot in every run manifest.
- Record strategy id on status, attempts, risk decisions, and performance summaries.
- Keep generated run artifacts and private live evidence out of Git.

## Testing Decisions

- Test external behavior, not implementation details.
- Add unit tests for the expensive YES decision rule: trade at ask `0.65`, skip below threshold, skip missing ask, skip stale quote, choose only YES, and size to one contract-equivalent under default caps.
- Add runtime/config tests proving `expensive_yes_live` seeds and saves independently from `fair_value_live`.
- Add dashboard service/API tests proving config save/read/status/performance can target the expensive YES strategy without changing fair-value config.
- Add live risk tests, or extend existing ones, proving per-strategy risk state stays isolated.
- Add runtime smoke tests proving paper/live-disabled runs materialize skip/trade evidence without submitting live orders.
- Add regression tests proving existing fair-value live tests still pass unchanged.

## Out of Scope

- Longer-window 7d/30d/60d research.
- Claiming the strategy is profitable or promotion-grade.
- Model changes, fair-value formula changes, or model registry promotion.
- New Strategy Studio compiler work.
- New Cockpit architecture or major dashboard redesign.
- New guardrail systems, approval flows, RBAC, OAuth, or security architecture.
- Maker/post-only execution.
- Order-book replay or fill modeling beyond compact live evidence.
- Current MVP cutover or changing which runtime is authoritative for live trading.
- Broad performance analytics beyond the compact status/performance needed to supervise the microprobe.

## Further Notes

This PRD is intentionally narrow. The goal is to answer "why not trade it?" with a tiny, observable live probe instead of more notebook-only debate. A good outcome is not immediate profit; a good outcome is knowing whether the expensive YES rule produces real fills, tolerable slippage, clean skips, and interpretable settlement outcomes under tiny risk.
