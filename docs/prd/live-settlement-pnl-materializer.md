# PRD: Live Settlement P&L Materializer

Linear publish status: published as
[ALP-291](https://linear.app/threadfork/issue/ALP-291/prd-live-settlement-pandl-materializer).

## Problem Statement

Operators can see that live strategy order attempts were submitted and filled,
but they do not have a canonical Operational State-backed answer for final
realized P&L once Kalshi finalizes the market. The current live artifacts can
prove execution, but compact reconciliation may continue to label filled
attempts as unsettled because it deliberately avoids public settlement lookup.
That forces operators and agents to reconstruct P&L by scanning artifacts,
querying public Kalshi market results manually, and recomputing payout, fees,
win rate, and exposure outside the product surface.

This was exposed during the BRTI-primary `fair_value_live` investigation: the
live filled attempts were real, the market results were finalized, and manual
inspection showed realized P&L, but AlphaDB did not have a boring canonical row
that Cockpit, reports, and agents could read.

## Solution

Build a narrow Live Settlement P&L Materializer that reconciles live order
attempts against public Kalshi finalized market outcomes and persists canonical
reconciliation rows in Operational State.

From the user's perspective, AlphaDB should be able to answer live operational
performance questions directly:

- realized P&L
- open or unsettled exposure
- gross cost
- fees
- payout
- filled contracts
- settled and unresolved counts
- win rate
- later risk/performance ratios using the same canonical rows

This is an operational reconciliation feature, not an official account-audit
system and not a settlement-state research system. It applies to all live
strategies that write live order attempts, starting with `fair_value_live`. BRTI
is preserved as decision provenance, but P&L calculation does not depend on
whether the decision source was BRTI, Coinbase, fixture, or something else.

## User Stories

1. As a live strategy operator, I want realized P&L to appear from canonical Operational State, so that I do not have to manually scan S3 artifacts.
2. As a live strategy operator, I want filled live attempts to settle once Kalshi finalizes their markets, so that performance reports stop showing stale unresolved rows.
3. As a live strategy operator, I want open exposure to remain visible for filled attempts whose market result is not yet finalized, so that I understand capital still at risk.
4. As a live strategy operator, I want no-fill attempts to be represented with zero P&L, so that skipped or unfilled activity does not pollute trade performance.
5. As a live strategy operator, I want partial fills to compute P&L only on filled contracts, so that reported performance matches actual exposure.
6. As a live strategy operator, I want gross cost, fees, payout, and net P&L separated, so that I can inspect why a trade won or lost money.
7. As a live strategy operator, I want win rate to use settled live reconciliation rows, so that it reflects final market outcomes rather than submitted-order counts.
8. As a live strategy operator, I want unresolved counts to be explicit, so that I know when a performance answer is incomplete.
9. As a live strategy operator, I want lookup failures to be recorded per market, so that one bad public API response does not hide all other reconciliations.
10. As a live strategy operator, I want rerunning reconciliation to update existing rows rather than creating duplicates, so that the operational ledger stays stable.
11. As a live strategy operator, I want the reconciliation command to be safe to run manually, so that I can answer urgent P&L questions after live probes.
12. As a live strategy operator, I want the reconciliation path to work for `fair_value_live`, so that BRTI-primary live-money probe results are reportable.
13. As a live strategy operator, I want the reconciliation path to be strategy-scoped, so that I can inspect one strategy without mixing unrelated live probes.
14. As a live strategy operator, I want decision source provenance preserved, so that BRTI-primary and Coinbase-primary results can be compared later.
15. As a live strategy operator, I want settlement source provenance preserved, so that I know whether a row was settled from public Kalshi market results.
16. As a live strategy operator, I want reconciled timestamps and observed timestamps, so that I know when AlphaDB looked and what market state it observed.
17. As a Cockpit user, I want the Performance section to read canonical live reconciliation rows, so that the UI answers P&L questions without frontend-owned trading logic.
18. As a Cockpit user, I want sparse or unavailable states to remain truthful, so that missing reconciliation data is not disguised as fake zero P&L.
19. As an agent, I want one canonical Operational State view of live settlement and P&L, so that natural-language performance questions do not require ad hoc scripts.
20. As an agent, I want settled and unresolved rows to be machine-readable, so that I can explain what evidence backs a P&L answer.
21. As an agent, I want strategy, run, market ticker, side, fill, cost, fee, payout, and result fields available together, so that I can audit individual trades.
22. As a runtime maintainer, I want reconciliation to stay outside the one-minute live decision hot path, so that trading authority remains fail-closed and bounded.
23. As a runtime maintainer, I want bounded live-risk admission refresh to remain separate from P&L settlement, so that admission control is not coupled to full-history reconciliation.
24. As a runtime maintainer, I want live order attempts to remain the execution evidence source, so that reconciliation does not create a parallel order lifecycle.
25. As a platform engineer, I want an idempotent upsert keyed to the live order attempt, so that the schema supports repeated reconciliation jobs.
26. As a platform engineer, I want a small pure P&L calculator interface, so that settlement arithmetic can be tested without database or network dependencies.
27. As a platform engineer, I want the public Kalshi market-result lookup isolated behind a client interface, so that lookup failures and tests are easy to control.
28. As a platform engineer, I want repository methods for reading candidate attempts and upserting reconciliation rows, so that Operational State ownership stays in Python.
29. As a platform engineer, I want the AlphaDB API performance summary to prefer live reconciliation rows for live strategies, so that Cockpit does not need direct database access.
30. As a platform engineer, I want lookup failure metadata stored in reconciliation rows, so that operational debugging does not depend on logs alone.
31. As a platform engineer, I want historical diagnostic artifact reconciliation to remain separate from this canonical table, so that old S3 reports do not become live authority.
32. As a researcher, I want this feature not to create an official BRTI settlement-state dataset, so that research provenance and licensed data policies remain clean.
33. As a researcher, I want this feature not to change model evaluation replay, so that operational P&L and research replay remain separate evidence systems.
34. As a risk reviewer, I want this feature not to change live trading policy, so that `0.999` near-settlement trading behavior can be evaluated separately.
35. As a risk reviewer, I want unresolved filled exposure visible, so that daily risk discussions can distinguish realized losses from still-open settlement exposure.
36. As a maintainer, I want tests for wins, losses, no-fills, unresolved markets, lookup failures, partial fills, and reruns, so that future changes do not regress basic P&L truth.

## Implementation Decisions

- Add a canonical `live_trade_reconciliations` Operational State table rather than expanding diagnostic artifact reports into product authority.
- Key reconciliation rows by live order attempt, using an upsert so reruns update the same row rather than appending duplicates.
- Include strategy, run, market ticker, side, filled contracts, cost, fees, market status, market result, settlement status, payout, net P&L, unsettled exposure, decision source, settlement source, settlement observed timestamp, reconciled timestamp, and metadata.
- Preserve decision provenance separately from settlement provenance. Decision provenance captures sources such as `brti_primary` or `coinbase_primary`; settlement provenance captures the public Kalshi market-result lookup used for operational reconciliation.
- Treat live order attempts as the execution evidence source. The reconciliation materializer reads attempts and does not mutate attempt lifecycle state except through explicit linking if a future implementation chooses to add a reference.
- Compute P&L from confirmed filled contracts. Submitted-but-unfilled attempts do not count as realized exposure unless fill evidence exists.
- Use actual cost and fee fields when available from the live attempt or order detail. If the MVP must fall back to intended price and configured fee assumptions, record that fallback in metadata.
- Compute payout as filled contracts times one dollar when the attempted side matches the finalized market result; otherwise payout is zero.
- Compute net P&L as payout minus cost and fees.
- Compute unsettled exposure as cost plus fees for filled attempts whose market result is not finalized or unavailable.
- Represent no-fill attempts with a no-fill settlement status and zero payout, zero net P&L, and zero unsettled exposure.
- Represent finalized wins, finalized losses, and flat outcomes distinctly enough for reports to compute win rate without guessing from numeric P&L alone.
- Represent lookup failures separately from ordinary open markets, so operators can distinguish public API problems from not-yet-finalized markets.
- Isolate Kalshi public market lookup behind a small client interface with per-market soft failure behavior.
- Cache or reuse market-result lookups within a run so multiple attempts in the same market do not require duplicate network calls.
- Add a live-orders command for settlement reconciliation, strategy-scoped by default and initially supporting `fair_value_live`.
- Keep reconciliation outside the one-minute live decision job and outside bounded live-risk admission refresh.
- Update the AlphaDB API performance summary path so live strategies prefer canonical live reconciliation rows before falling back to sparse or unavailable states.
- Keep Cockpit as a reader of AlphaDB API performance output only; Cockpit does not compute P&L or query Operational State directly.
- Keep artifact-level live reconciliation as diagnostic compatibility, not the canonical answer for operational P&L.
- Do not introduce official BRTI settlement-state reconstruction in this PRD. BRTI remains decision-time market context, not settlement truth for this operational materializer.
- Do not use this PRD to decide whether high-price near-settlement trades are desirable. That is a separate strategy/risk policy decision.
- Major modules to build or modify are: Operational State schema and repository methods, a pure live settlement P&L calculator, a Kalshi public market-result client, the live-orders command surface, the AlphaDB API performance summary projection, and Cockpit/reporting consumers as needed to display the new fields.
- The deepest module should be the reconciliation calculator/materializer interface: given attempt fill facts and a market-result observation, it returns a deterministic reconciliation row. This keeps arithmetic and status decisions testable without network or database state.

## Testing Decisions

- Tests should assert external behavior: persisted rows, status transitions, summary fields, CLI output, and API response payloads. They should not lock tests to implementation-private helper names.
- Add pure unit tests for the settlement P&L calculator covering settled win, settled loss, settled flat, no-fill, unresolved market, lookup failure, partial fill, fee fallback, and cost fallback.
- Add repository tests that prove migrations create the reconciliation table, candidate live attempts can be selected by strategy, reconciliation rows can be upserted, and reruns do not create duplicates.
- Add command tests using a fake market-result client and local Operational State so the command can prove soft failure behavior without real Kalshi network calls.
- Add performance summary tests proving live reconciliation rows produce realized P&L, unsettled exposure, gross cost, fees, payout, filled contracts, settled count, open count, and win rate.
- Add tests proving no live reconciliation data produces truthful unavailable or sparse performance states rather than fake zeros.
- Add tests proving multiple live attempts in the same market can reconcile from one market-result observation without inconsistent row outcomes.
- Add tests proving lookup failure for one market does not prevent other markets from reconciling.
- Add tests proving no-fill attempts produce zero P&L and do not count as wins or losses.
- Add tests proving partial fills compute cost, fees, payout, and exposure from filled quantity rather than intended quantity.
- Add tests proving the AlphaDB API remains the boundary for Cockpit performance data.
- Prior art in the codebase includes live order repository tests, live runtime tests around reconciliation-shaped rows, performance summary tests, model evaluation replay P&L tests, and synthetic settlement-state tests.

## Out of Scope

- Official BRTI settlement-state reconstruction.
- Licensed official BRTI dataset ingestion or publication.
- Promotion-grade research datasets.
- Model evaluation replay changes.
- Full exchange account reconciliation.
- Maker-order lifecycle or resting-order state machines.
- New trading behavior, edge thresholds, max-price caps, or live-risk authority changes.
- Changes to bounded live-risk admission refresh.
- Mutation of live order attempt lifecycle state beyond reading and optional explicit linkage.
- Cockpit-owned P&L logic or direct Cockpit database access.
- Historical S3 artifact backfill as the main MVP path.
- Sharpe and Sortino implementation, except that future ratios should use this canonical table once present.

## Further Notes

The BRTI-primary investigation found 43 filled attempt rows across 16 finalized
markets. All were `0.999` near-certain-side fills, all matched the public Kalshi
result, and manual public-market lookup produced positive realized P&L. That
proved the reporting gap: the compact live artifacts could still report
unresolved or zero realized P&L even when operational P&L was knowable.

This PRD addresses the canonical P&L and settlement reporting gap. It
intentionally does not answer whether near-settlement `0.999` trades should be
allowed. That should be handled by a separate strategy diagnosis or risk-policy
issue covering max price, minimum edge after fees, and late-window trading
behavior.
