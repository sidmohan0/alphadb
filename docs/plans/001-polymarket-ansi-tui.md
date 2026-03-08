# 001: Polymarket ANSI TUI

## Goal

Build a terminal UI with excellent keyboard UX for:

- browsing trending Polymarket markets
- searching markets quickly
- switching between market outcomes
- viewing outcome price action as ANSI candlesticks

## Product Shape

- Left pane: searchable market table
- Right pane: candlestick chart plus market metadata
- Footer: compact control guide and status line
- Preview model: moving selection updates the chart without requiring a separate confirm screen

## Data Plan

- Gamma `/markets`
  - source for trending market rows and metadata
  - sorted by `volume24hr`
- Gamma `/public-search`
  - source for interactive search results
- CLOB `/prices-history`
  - source for token price time series
  - local candle aggregation for chart rendering

## UX Priorities

- fast selection movement
- obvious focus state
- graceful loading and error states
- compact, readable tables on 80-column terminals
- richer layout on wider terminals
- persistent saved markets and recents
- search ranking that uses both text quality and market quality

## Implementation Notes

- Node + TypeScript, no framework
- raw-mode terminal input
- alternate-screen rendering
- ANSI colors and box-drawing characters
- resize-aware layout

## Verification

- `npm run typecheck`
- `npm run build`
- live smoke run against public Polymarket endpoints
