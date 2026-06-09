# Live Risk Daily Loss Cap Diagnosis

## Current Status / Risk Action

- No schedule, live-order enablement flag, or exchange credential behavior is changed by this note.
- The fix is scoped to live risk admission/accounting semantics for the current live risk day.

## Observed Underperformance

- The live daily-loss value could increase when open or pending exposure changed, even when realized daily loss was unchanged.
- The affected scope is the `fair_value_live` live risk admission state and status payloads consumed by the Cockpit and legacy dashboard surfaces.

## Evidence Inspected

- `CONTEXT.md` live risk vocabulary.
- `docs/strategy/fair-value-live-strategy.md` runtime/risk description.
- `src/alphadb/live_risk.py` admission state and cap enforcement.
- `src/alphadb/model_evaluation/fair_value_live_job.py` live-risk accounting and attempt payload construction.
- Existing live-risk and fair-value live tests around daily cap behavior.

## Suspected Failure Modes

- The strongest implementation defect was that `daily_loss_used_dollars` and `daily_loss_used_before_dollars` were populated from total risk used: realized daily loss plus open exposure plus pending exposure.
- This made the operator-facing daily-loss value look like it was climbing for exposure changes unrelated to realized loss.
- It also made daily-loss cap admission compare against the combined total risk number rather than realized live-risk-day loss.

## One Next Experiment

- Run focused repository and live-job tests that seed realized loss separately from open exposure, then verify admission, attempt payloads, and accounting reports keep those quantities separate.

## Proposed Code / Config Changes

- Use realized live-risk-day loss for daily-loss cap admission and `daily_loss_*` reporting fields.
- Continue tracking open exposure, pending exposure, and per-market exposure as separate live risk admission state fields.
- Preserve existing API field names for compatibility, but clarify docs and UI labels so `daily_loss_used_dollars` means realized daily loss, not total exposure.
- Add a Cockpit config-panel reset action that clears realized daily loss for the active live risk day while preserving open exposure, pending exposure, and pending reservations.
