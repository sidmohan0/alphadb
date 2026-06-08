# CF Benchmarks Value Feed Research Fit

Status: research assessment
Reviewed: 2026-06-08
Branch: `exp/cfbenchmarks-value-research-fit`

## Source Summary

Kalshi's `cfbenchmarks_value` WebSocket channel emits real-time CF Benchmarks
index values. The channel requires an authenticated WebSocket connection, is
subscribed by `index_ids`, supports `index_ids: ["all"]`, can return an
`indexlist`, and emits ticks roughly once per second. Each value update includes
the index id, Kalshi receive timestamp, the raw upstream frame, a trailing
60-second average, and a final-minute quarter-hour average that is present only
inside the final minute before `:00`, `:15`, `:30`, and `:45` quarter closes.
Kalshi documents that final-minute field as excluding the start boundary and
including the close tick: `(quarter_close_ts_ms - 60000, quarter_close_ts_ms]`.

Primary source:

- <https://docs.kalshi.com/websockets/cfbenchmarks-value>
- <https://docs.kalshi.com/websockets>
- <https://docs.kalshi.com/getting_started/quick_start_websockets>

## Fit Verdict

This feed is a strong fit for an AlphaDB experiment, but it should enter as a
research input and future raw event source, not as immediate model-promotion,
live-trading, or Current MVP cutover authority.

The useful split is:

- Settlement-state validation input: capture `BRTI` around `KXBTC15M` quarter
  closes and compare the final-minute average to AlphaDB settlement-state
  calculations.
- Decision-time context feed: create no-lookahead threshold-distance,
  current-index, short-window momentum, and final-minute-lockdown features for
  fair-value policy replay.
- WebSocket ingestion readiness probe: validate authenticated subscription,
  sequencing, reconnect, and coverage behavior before serious paper or shadow
  runtime use.

## Boundary Classification

For `KXBTC15M`, the feed is official-source-adjacent because the market rules
already identify CF Benchmarks as the source agency and the settlement spec uses
the `BRTI` index with a final 60-second average. However, AlphaDB should not
automatically treat a Kalshi-relayed live WebSocket stream as
`official_licensed` historical settlement input.

Until licensing and retention rights are confirmed, store generated captures
outside Git and classify derived manifests as public-safe evidence. In the
current settlement manifest contract, promotion-grade settlement readiness still
requires `source_status == "official_licensed"`. A feed capture with uncertain
license status should produce an `INCONCLUSIVE` readiness verdict, not a
`PASS`, even if the mechanics look correct.

For feature research, the feed behaves like external market context. A feature
row may use a CF Benchmarks tick only if the source timestamp and local receive
timestamp prove it was observable at or before the decision timestamp. Historical
backfills must preserve retrieval timing and must not pretend that later
collection was live-observable.

AlphaDB now adopts Kalshi's documented `cfbenchmarks_value` quarter-close
average convention for `KXBTC15M` settlement-state calculations: the final
minute excludes the start-boundary tick and includes the close tick,
`(close - 60s, close]`. For one-second `BRTI` prints, that means `close - 59s`
through `close`.

## Proposed Research Questions

1. Coverage and latency: can AlphaDB capture continuous `BRTI` values through
   enough quarter-hour closes without missing final-window data?
2. Settlement mechanics: does the captured final-minute quarter-hour average
   match AlphaDB's close-inclusive final 60 one-second average over normalized
   official settlement input or exchange-published outcomes, subject to
   documented precision and rounding semantics?
3. Model value: do CF Benchmarks decision-time features improve probability
   quality and taker-policy outcomes after fees and spread stress versus the
   Coinbase/BTC market-structure baseline?
4. Operational readiness: can the existing `alphadb.collectors.kalshi_ws`
   raw-event path be extended to index-level events without forcing a
   market-ticker join in the hot path?

## First Experiment Shape

Start with a narrow capture probe before any runtime or model changes:

- Subscribe to `cfbenchmarks_value` for `index_ids: ["BRTI"]`.
- Call `indexlist` once per run and preserve the returned available index ids.
- Capture raw value frames across at least several `KXBTC15M` quarter-hour
  closes, including the full final minute before close.
- Store raw frames under ignored `research/` or `artifacts/` paths.
- Normalize a private table with index id, source timestamp, Kalshi receive
  timestamp, local receive timestamp, sequence, raw upstream payload hash,
  tick value, trailing 60-second average, and quarter-hour final-minute average.
- Produce a public-safe manifest with counts, time range, gaps, hashes, source
  status, index ids, websocket environment, and a readiness verdict.
- Only after coverage is credible, run an offline feature ablation against
  decision-time rows and settlement labels.

## Schema Notes

The existing raw event log can hold index-level feed events because
`raw_events.market_ticker` is nullable. A future implementation can use:

- `source`: `kalshi_ws`
- `schema_version`: `kalshi.ws.cfbenchmarks_value.v1`
- `source_event_id`: `cfbenchmarks_value:{index_id}:{source_ts_ms}:{seq}`
- `market_ticker`: `null` for raw index events
- `source_timestamp`: parsed upstream `time` from `msg.data`
- `payload`: the complete Kalshi message plus parsed convenience fields

Market-instance joins should happen in normalized research or feature-building
steps, where a `BRTI` tick can be associated with all active `KXBTC15M` markets
whose decision or settlement window can legally observe it.

## Promotion Gates

Do not promote this feed beyond research until these are resolved:

- Retention and licensing status for Kalshi-relayed CF Benchmarks frames.
- Exact timestamp semantics for upstream `time`, Kalshi `received_at`, and local
  receive time.
- Rounding and precision behavior for settlement comparison.
- Behavior during missing ticks, duplicate timestamps, reconnects, and final
  close ticks.
- Whether the demo environment supports representative `cfbenchmarks_value`
  payloads and index ids.

Passing the first capture probe should create an edge verdict or readiness
verdict only. It should not authorize model registry promotion, live trading,
Current MVP changes, or target-platform cutover.
