# CF Benchmarks Value Feed Experiment

Status: design-only scaffold
Related assessment: `docs/research/cfbenchmarks-value-feed-fit.md`

## Hypothesis

The Kalshi `cfbenchmarks_value` WebSocket feed can improve AlphaDB's
`KXBTC15M` research foundation by providing observable, one-second `BRTI`
index context and final-minute quarter-hour averages, as long as captures are
manifested, no-lookahead-safe, and kept separate from promotion-grade official
licensed settlement history until source rights are confirmed.

## Non-Goals

- No live trading or order submission.
- No Current MVP integration.
- No model registry promotion.
- No committed raw CF Benchmarks, official BRTI, or private generated datasets.
- No assumption that a live Kalshi relay is automatically licensed historical
  settlement input.

## Data Contract

Capture runs should preserve:

- WebSocket environment and URL family, without credentials.
- Subscription command ids, assigned `sid`, requested `index_ids`, and
  `indexlist` response.
- Raw `cfbenchmarks_value` messages exactly as received.
- Local receive timestamps in UTC.
- Parsed upstream source timestamp and value from `msg.data`.
- Kalshi `received_at`, stream `seq`, `avg_60s_data`, and
  `last_60s_windowed_average_15min`.
- Coverage gaps, reconnect intervals, duplicate/out-of-order drops if observed,
  and final-window completeness.
- File hashes and row counts for every generated artifact.

## Candidate Outputs

Private generated outputs:

- `research/cfbenchmarks-value-feed/<dataset_id>/raw/ws_frames.jsonl`
- `research/cfbenchmarks-value-feed/<dataset_id>/normalized/index_ticks.parquet`
- `research/cfbenchmarks-value-feed/<dataset_id>/derived/final_windows.parquet`
- `artifacts/cfbenchmarks-value-feed/<dataset_id>/coverage_report.md`

Public-safe committed outputs:

- A pull manifest based on `templates/pull_manifest.example.json`.
- A dataset manifest based on `templates/dataset_manifest.example.json`.
- A short decision record under `decisions/` when the probe has a verdict.

## Success Criteria

The first probe is useful if it can answer:

- Were all intended quarter-hour final windows captured?
- Did the feed provide 60 final-minute observations for complete closes?
- Were source timestamps, Kalshi receive timestamps, and local receive
  timestamps internally consistent?
- Did captured final-window averages match AlphaDB's adopted close-inclusive
  `(close - 60s, close]` convention?
- Can the private capture be transformed into settlement-state or feature rows
  without lookahead?
- Is the licensing/source-status strong enough for settlement-state readiness,
  or should the result stay `INCONCLUSIVE`?
