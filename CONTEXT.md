# Context

## Project

AlphaDB is the target-platform repo for a reusable Kalshi prediction-market trading platform. It starts with `KXBTC15M`, but the architecture should support future crypto market families through explicit market specifications.

## Vocabulary

- **Target platform**: The reusable Kalshi prediction-market trading platform north star that generalizes the current `KXBTC15M` MVP across market families while preserving replayability, auditability, and risk controls.
- **Current MVP**: The existing Kalshi repo and live `KXBTC15M` runner that remains authoritative until target-platform cutover.
- **Platform architecture PRD**: An umbrella PRD that describes the target platform and milestone sequence; implementation should happen through smaller child issues rather than one large rewrite.
- **MarketSpec**: Target-platform configuration object that defines a tradable market family's series, underlying, horizon, settlement source, discovery rules, feature config, label function, fee assumptions, risk config, and trading cutoffs.
- **SettlementSpec**: Structured settlement-rules contract for a market family, including the required official input source, payout threshold rule, payout comparator semantics, final settlement window rule, expected print cadence, missing/duplicate print policy, and authoritative timestamp semantics.
- **Market instance**: One concrete contract window inside a recurring market series.
- **Handle every instance**: Operational invariant that each eligible market instance must receive exactly one authoritative trade or skip outcome.
- **Shared decision engine**: Target-platform component that turns market state, features, model output, executable quotes, policy config, and risk state into an order intent or skip decision independent of runtime mode.
- **Target platform operational state**: Transactional Postgres state used by the target platform for runs, decisions, risk decisions, orders, fills, positions, reconciliation, and model registry records.
- **Model registry**: Target-platform operational registry that records which model artifacts, feature versions, calibration versions, dataset ids, and promotion states are approved or available for use.
- **Model evaluation report**: Generated research artifact that compares model artifacts, feature schemas, dataset ids, probability metrics, calibration, policy metrics, stress scenarios, and live/paper attribution context without by itself authorizing promotion or live trading.
- **Fair-value policy replay**: Model evaluation run that applies a fair-value policy to decision-time rows, executable quotes, fee assumptions, and settlement labels to produce trades, skips, PnL, and settlement reconciliation without reconstructing raw events.
- **Edge verdict**: Fast research conclusion about whether a feature or model branch has tradable promise. An edge verdict must consider probability quality and taker-policy outcomes after fees and spread stress on holdout or walk-forward slices; better probability metrics alone are not enough. Edge verdicts do not authorize model promotion, live trading, Current MVP changes, or target-platform cutover.
- **External signal source**: Third-party observable information source, such as X API counts, X News metadata, RSS feeds, GDELT, or exchange status feeds, used to create decision-time context features. External signal sources are feature inputs only; they are not settlement truth sources and do not by themselves authorize model promotion or live trading.
- **External signal research dataset**: Generated private or ignored research artifact that captures historical external signals for a tested time range, including source timestamps, retrieval timestamps, query catalog version, cost metadata, payload hashes, and no-lookahead fields. Initial X work should produce this kind of dataset before any target-platform live ingestion is introduced.
- **External signal feature-set manifest**: Public-safe provenance record for a private external signal research dataset, including source identity, query catalog version, tested time range, coverage counts, feature names, exclusion reasons, estimated and actual API cost, artifact hashes, artifact locations, and whether the dataset is suitable for model evaluation.
- **Coinbase/BTC market-structure feature set**: Decision-time feature family derived from observable Coinbase/BTC market data, such as momentum, volatility, realized range, threshold distance, reversals, shocks, and liquidity or order-book context when available. This feature set is external market context, not settlement truth, and must preserve no-lookahead lineage.
- **Official BRTI research input**: Licensed or otherwise private one-second BRTI history used to reconstruct crypto settlement state for research validation. Raw official BRTI prints are never committed to the public repo.
- **Normalized official settlement input**: Local or object-storage-backed official settlement data converted into a stable private schema for validation and research. Initial settlement-state readiness consumes this normalized input instead of owning vendor-specific download/auth flows.
- **Settlement state**: Point-in-time view of how much of a market instance's settlement calculation is already fixed, what remains uncertain, and whether the available source data is sufficient to use that view for research validation.
- **Settlement-state readiness**: The prerequisite validation milestone that proves official settlement inputs, market rules, source-quality checks, and no-lookahead audit fields are trustworthy enough for downstream fair-value or edge research. It does not include fair-value modeling, backtesting, promotion, or live-trading authorization.
- **Readiness verdict**: A `PASS`, `FAIL`, or `INCONCLUSIVE` conclusion on whether a research foundation is trustworthy enough for its downstream purpose. `INCONCLUSIVE` is a valid outcome when implementation exists but coverage, licensing, source quality, or rule clarity is insufficient for promotion-grade research.
- **Payout threshold**: The market-rule-defined price level used to decide whether a market instance pays out. For `KXBTC15M`, the threshold is a listed strike from the concrete market metadata, not an opening-window-derived reference value based on the reviewed `CRYPTO15M.pdf` terms.
- **Payout comparator semantics**: Rules that define how an expiration value is compared with a payout threshold. For `KXBTC15M`, the reviewed `CRYPTO15M.pdf` terms define `above` and `below` as strict comparisons, `exactly` as equality at the specified precision, `at least` as inclusive lower-bound comparison, and `between` as inclusive on both endpoints.
- **Valid settlement-state row**: A settlement-state record whose market metadata, official settlement inputs, decision timestamp, source timestamps, and quality flags are internally consistent and safe to use in downstream promotion-grade research. Invalid rows may be retained for auditability but must be excluded from promotion-grade fair-value and edge tests.
- **Settlement-state dataset**: Generated research artifact that reconstructs a market instance's settlement state from official BRTI and market metadata, including the payout threshold, payout comparator, final settlement window, locked prints, remaining prints, quality flags, and no-lookahead audit fields. Full datasets stay outside Git and are referenced by manifests and hashes.
- **Settlement-state manifest**: Public, shareable provenance record for a private settlement-state dataset, including source status, schema version, code version, tested time range, coverage counts, exclusion reasons, artifact hashes, artifact locations, and readiness verdict.
- **Raw event log**: Append-only target-platform record of Kalshi REST snapshots, Kalshi WebSocket events, external feature events, and execution events with receive timestamps, source identity, schema version, payload hash, and raw payload.
- **Event-driven replay**: Target-platform simulation or diagnostic run that reconstructs market state, features, risk decisions, orders, fills, positions, and PnL from raw event logs and immutable artifacts.
- **REST-first target ingestion**: Initial target-platform ingestion slice that records Kalshi REST snapshots and external feature events as raw event logs before authenticated WebSocket ingestion is added.
- **Shadow platform run**: A non-authoritative target-platform run that consumes the same market instances as the current MVP and compares decisions, features, predictions, risk outcomes, and simulated orders without controlling live trading.
- **Live-data paper run**: A non-authoritative target-platform run that uses live market and feature data to make and paper-execute decisions without depending on the Current MVP or submitting real orders.
- **Decision-boundary equivalence**: Shadow-run comparison standard where the target platform must match the current MVP's feature row, model artifact, probability, executable quotes, expected values, selected side or skip reason, risk result, and intended order size for the same market instance and decision timestamp.
- **Gated-live runtime mode**: Target-platform runtime mode where live order-submission code is wired and testable but disabled unless explicit live configuration and human cutover approval are present.
- **Live platform cutover**: The moment the target platform becomes authoritative for live trading after shadow runs prove equivalence or intentionally documented differences.
- **Taker-only execution policy**: Initial execution policy that submits immediate-or-cancel style orders at observed executable prices and does not intentionally rest maker/post-only orders.
- **Maker execution policy**: Future execution policy that may rest post-only orders and therefore requires order-book replay, fill modeling, adverse-selection analysis, cancellation maturity, and explicit risk enablement.
- **Target platform dashboard**: Live-first operator console for live operations, dashboard-owned non-secret runtime config, curated risk/status panels, recent attempts, research/replay diagnostics, and model registry visibility.
- **Target platform dev environment**: Dev Container backed by Docker Compose that provides the reproducible local runtime for Postgres, target-platform services, and the dashboard.

## Relationships

- The **Current MVP** remains authoritative until **Live platform cutover**.
- A **Live-data paper run** can prove AlphaDB's independent runtime before **Shadow platform runs** compare it against the **Current MVP**.
- The **Target platform** should prove **Decision-boundary equivalence** through **Shadow platform runs** before live cutover.
- **Gated-live runtime mode** may be implemented before **Live platform cutover**, but it must fail closed unless the human cutover gate is satisfied.
- The **Shared decision engine** should be reused across historical replay, shadow runs, paper trading, and live trading; only the event source, clock, and exchange adapter should vary by runtime mode.
- A strategy should **Handle every instance** by producing either an order intent or a skip decision; submitting an order for every instance is a policy choice, not a platform invariant.
- **Target platform operational state** lives in Postgres from the start.
- The **Model registry** lives in Postgres, while model binaries, feature schemas, reports, and dataset manifests remain immutable file or object-storage artifacts referenced by hash.
- **Model evaluation reports** may inform model registry promotion decisions, but promotion still requires explicit policy gates and human approval where required by the target-platform milestone.
- **Fair-value policy replay** is a kind of **Model evaluation report**, not an **Event-driven replay**; it consumes decision rows and settlement labels rather than raw event logs.
- An **Edge verdict** may justify the next research branch, but it is not a model promotion gate and cannot authorize live trading or target-platform cutover.
- The public repo may include data schemas, validation code, synthetic fixtures, and artifact manifests, but official/licensed market data and full generated research datasets remain outside Git.
- Initial X API work should create an **External signal research dataset** and **External signal feature-set manifest** for offline model evaluation before X becomes an operational raw event source for shadow, paper, or live runs.
- External signal features must be joined to market decisions using only source events observable at or before the decision timestamp; retrieval time and source event time must both be recorded so no-lookahead audits can distinguish late collection from historical observability.
- Raw X API counts were tested as a cheap, backfillable external signal research dataset, but the first real holdout comparison made baseline `KXBTC15M` model metrics worse. The raw-count branch should stay frozen unless it is reframed as event-shock, spike, or sparse alert features with explicit evidence.
- The next external-feature research branch should prioritize the **Coinbase/BTC market-structure feature set** before additional broad social/news collection.
- Future X API research should use a small, versioned query catalog of named categories rather than a broad open-ended topic sweep, so feature ablations remain interpretable and resistant to holdout overfitting.
- **Settlement state** is a reusable target-platform concept, with `KXBTC15M` as the first concrete market family supported by settlement-state reconstruction.
- Settlement-state reconstruction should be driven by structured settlement rules rather than free-text settlement descriptions. The first `SettlementSpec` may support only `KXBTC15M`'s listed payout threshold and final 60 one-second average.
- Initial settlement-state readiness should consume normalized official settlement input from private storage; vendor-specific acquisition/download flows belong in later work once the source is chosen.
- Settlement-state readiness depends on strict per-row validity and explicit coverage reporting rather than assuming all source data is perfect or requiring a universal coverage percentage before real source quality is known.
- A settlement-state readiness `PASS` requires the relevant payout threshold source and comparator semantics to be documented, implemented, and validated; ambiguous payout rules force `INCONCLUSIVE` or `FAIL`.
- Settlement-state calculators should support arbitrary decision timestamps; scheduled offsets such as the Current MVP's minute-12 decision are convenience sampling policies, not a limitation of the settlement-state concept.
- Initial settlement-state readiness should produce offline research artifacts and public manifests, not operational Postgres records. Operational storage belongs in later work if settlement state becomes part of shadow, paper, or live decisioning.
- Public synthetic fixtures should exercise settlement-state mechanics and edge cases without exposing licensed official settlement inputs or private research datasets.
- Settlement-state readiness outputs should be manifest-first: downstream fair-value and edge research should depend on dataset manifests and hashes rather than implicit local files.
- **REST-first target ingestion** may prove target-platform boundaries and shadow comparison, but authenticated Kalshi WebSocket ingestion is required before serious paper/live promotion.
- The target platform should preserve **Taker-only execution policy** as the first paper/live execution mode; **Maker execution policy** belongs in a later milestone and must be explicitly enabled by risk config.
- The **Target platform dashboard** should open on the Live operator workspace.
- The **Target platform dev environment** is part of the first target-platform milestone.
