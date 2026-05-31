# Context

## Project

AlphaDB is the target-platform repo for a reusable Kalshi prediction-market trading platform. It starts with `KXBTC15M`, but the architecture should support future crypto market families through explicit market specifications.

## Vocabulary

- **Target platform**: The reusable Kalshi prediction-market trading platform north star that generalizes the current `KXBTC15M` MVP across market families while preserving replayability, auditability, and risk controls.
- **Current MVP**: The existing Kalshi repo and live `KXBTC15M` runner that remains authoritative until target-platform cutover.
- **Platform architecture PRD**: An umbrella PRD that describes the target platform and milestone sequence; implementation should happen through smaller child issues rather than one large rewrite.
- **MarketSpec**: Target-platform configuration object that defines a tradable market family's series, underlying, horizon, settlement source, discovery rules, feature config, label function, fee assumptions, risk config, and trading cutoffs.
- **Market instance**: One concrete contract window inside a recurring market series.
- **Handle every instance**: Operational invariant that each eligible market instance must receive exactly one authoritative trade or skip outcome.
- **Shared decision engine**: Target-platform component that turns market state, features, model output, executable quotes, policy config, and risk state into an order intent or skip decision independent of runtime mode.
- **Target platform operational state**: Transactional Postgres state used by the target platform for runs, decisions, risk decisions, orders, fills, positions, reconciliation, and model registry records.
- **Model registry**: Target-platform operational registry that records which model artifacts, feature versions, calibration versions, dataset ids, and promotion states are approved or available for use.
- **Raw event log**: Append-only target-platform record of Kalshi REST snapshots, Kalshi WebSocket events, external feature events, and execution events with receive timestamps, source identity, schema version, payload hash, and raw payload.
- **Event-driven replay**: Target-platform simulation or diagnostic run that reconstructs market state, features, risk decisions, orders, fills, positions, and PnL from raw event logs and immutable artifacts.
- **REST-first target ingestion**: Initial target-platform ingestion slice that records Kalshi REST snapshots and external feature events as raw event logs before authenticated WebSocket ingestion is added.
- **Shadow platform run**: A non-authoritative target-platform run that consumes the same market instances as the current MVP and compares decisions, features, predictions, risk outcomes, and simulated orders without controlling live trading.
- **Decision-boundary equivalence**: Shadow-run comparison standard where the target platform must match the current MVP's feature row, model artifact, probability, executable quotes, expected values, selected side or skip reason, risk result, and intended order size for the same market instance and decision timestamp.
- **Live platform cutover**: The moment the target platform becomes authoritative for live trading after shadow runs prove equivalence or intentionally documented differences.
- **Taker-only execution policy**: Initial execution policy that submits immediate-or-cancel style orders at observed executable prices and does not intentionally rest maker/post-only orders.
- **Maker execution policy**: Future execution policy that may rest post-only orders and therefore requires order-book replay, fill modeling, adverse-selection analysis, cancellation maturity, and explicit risk enablement.
- **Target platform dashboard**: Streamlit-first target-platform UI for research, replay diagnostics, paper trading, live operations, risk state, PnL, latency, and model registry visibility.
- **Target platform dev environment**: Dev Container backed by Docker Compose that provides the reproducible local runtime for Postgres, target-platform services, and Streamlit.

## Relationships

- The **Current MVP** remains authoritative until **Live platform cutover**.
- The **Target platform** should prove **Decision-boundary equivalence** through **Shadow platform runs** before live cutover.
- The **Shared decision engine** should be reused across historical replay, shadow runs, paper trading, and live trading; only the event source, clock, and exchange adapter should vary by runtime mode.
- A strategy should **Handle every instance** by producing either an order intent or a skip decision; submitting an order for every instance is a policy choice, not a platform invariant.
- **Target platform operational state** lives in Postgres from the start.
- The **Model registry** lives in Postgres, while model binaries, feature schemas, reports, and dataset manifests remain immutable file or object-storage artifacts referenced by hash.
- **REST-first target ingestion** may prove target-platform boundaries and shadow comparison, but authenticated Kalshi WebSocket ingestion is required before serious paper/live promotion.
- The target platform should preserve **Taker-only execution policy** as the first paper/live execution mode; **Maker execution policy** belongs in a later milestone and must be explicitly enabled by risk config.
- The **Target platform dashboard** should be Streamlit-first.
- The **Target platform dev environment** is part of the first target-platform milestone.
