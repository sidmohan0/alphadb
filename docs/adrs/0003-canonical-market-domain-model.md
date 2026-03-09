# ADR 0003: Canonical Market Domain Model

- Status: Accepted
- Date: 2026-03-09

## Context

Polymarket and Kalshi expose similar concepts with materially different identifiers, metadata, and market mechanics. The TUI already normalizes them enough to render a common interface, but a production backend needs a more durable model.

## Decision

Define a canonical market domain model with provider-specific extensions kept at the edges.

Core entities:

- `Provider`
- `Market`
- `Outcome`
- `Instrument`
- `Quote`
- `Trade`
- `Candle`
- `Event`
- `Series`
- `Watchlist`
- `SavedSearch`

Rules:

- canonical IDs are internal and stable
- provider IDs remain first-class foreign keys
- raw provider payloads are stored for traceability
- normalized fields are versioned
- provider-specific fields live in extension blobs or child tables

Normalization principles:

- one canonical market can map to one provider market only in v1
- cross-provider equivalence is modeled separately as a relationship, not by pretending markets are identical
- charts use canonical candle contracts regardless of source

## Consequences

Positive:

- enables multi-provider search and comparison cleanly
- avoids leaking provider quirks throughout the codebase
- makes future providers possible without rewriting clients

Negative:

- requires careful schema and versioning discipline
- mapping quality becomes a product concern, not a simple adapter concern

## Notes

Cross-provider comparison should be explicit and probabilistic. Do not encode “same market” unless the system can defend that mapping.
