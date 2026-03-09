# ADR 0005: Search, Discovery, And Ranking

- Status: Accepted
- Date: 2026-03-09

## Context

The TUI already blends provider search results with local signals such as saved/recent markets and volume. The backend branch already performs expensive discovery jobs and persistence. Production search should combine both ideas.

## Decision

Separate discovery from query serving.

Discovery path:

- provider crawlers and async jobs ingest market metadata
- enrichment jobs compute normalized attributes and comparison hints
- ranking features are precomputed where possible

Query path:

- backend search API serves from indexed normalized data
- clients send intent, not provider-specific API requests
- ranking combines text match, liquidity, activity, freshness, user affinity, and provider confidence

Ranking layers:

- lexical relevance
- exact/prefix boosts
- activity and liquidity boosts
- saved/recent personalization
- provider-quality or confidence modifiers
- optional experimental reranking in a shadow path

## Consequences

Positive:

- consistent search quality across TUI and web
- lets expensive discovery happen server-side
- supports curated and personalized ranking

Negative:

- requires index freshness and ranking calibration work
- search relevance becomes an owned subsystem, not a thin proxy

## Notes

Do not treat provider-native search as the production search backend. Use it only as a bootstrap or fallback source.
