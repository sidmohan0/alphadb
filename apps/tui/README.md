# AlphaDB Markets ANSI TUI

Terminal-first Polymarket and Kalshi browser built for fast market discovery, split-screen comparison, quick search, and readable price action without leaving the shell.

This app now lives inside the unified AlphaDB monorepo at `apps/tui`.

## What It Does

- Renders live Polymarket outcome history as ANSI candlesticks
- Adds Kalshi market discovery with optional live ticker support
- Boots into a unified split view with Polymarket on the left and Kalshi on the right
- Shows trending markets ranked by 24h volume
- Supports fuzzy market search with local ranking bonuses
- Persists saved markets and recent views between runs
- Keeps navigation keyboard-first with immediate chart preview on selection

## Getting Started

### Requirements

- Node.js 18+
- npm 9+

### Install

```bash
npm install
```

### Run In Development

```bash
npm run dev --workspace @alphadb/tui
```

To route market reads through the AlphaDB backend instead of hitting providers directly:

```bash
ALPHADB_API_BASE_URL=http://localhost:4000/api npm run dev --workspace @alphadb/tui
```

To seed backend saved/recent state for the default local user before launching the TUI:

```bash
npm run markets:seed-state
```

### Build And Run

```bash
npm run build --workspace @alphadb/tui
npm run start --workspace @alphadb/tui
```

## Keyboard Controls

### Navigation

- `1`: switch to Polymarket
- `2`: switch to Kalshi
- `3`: return to unified split view
- `j` / `k` or arrow keys: move selection
- `h` / `l` or left/right arrows: switch focus between unified panes
- `t`: show trending markets
- `v`: show saved markets
- `u`: show recent markets
- `/`: focus search
- `Tab`: move focus between list and search
- `Esc`: leave search and clear transient errors

### Market Actions

- `f`: save or unsave the selected market
- `o`: cycle market outcome
- `[` / `]`: change chart range
- `r`: refresh data
- `Enter`: run search or reload chart

### App

- `?`: toggle help
- `q`: quit

## Search Ranking

Search combines live Gamma `public-search` results with local candidates from:

- trending markets
- saved markets
- recent markets

Ranking favors:

- strong question/title matches
- prefix and substring matches
- subsequence-style fuzzy matches
- markets already returned by Gamma
- saved and recent markets
- higher-volume and higher-liquidity markets

## Persistence

The app stores saved markets and recents at:

```bash
~/.config/alphadb-tui/state.json
```

Override the location with:

```bash
ALPHADB_TUI_STATE_PATH=/custom/path/state.json
```

## Optional Kalshi Live Ticker

Kalshi market browsing works without credentials.

To enable authenticated Kalshi websocket ticker updates, set:

```bash
KALSHI_API_KEY_ID=...
KALSHI_PRIVATE_KEY_PATH=/path/to/private-key.pem
```

Or use:

```bash
KALSHI_PRIVATE_KEY_PEM='-----BEGIN PRIVATE KEY-----...'
```

## Data Sources

- Gamma API: trending markets, market metadata, search
- CLOB API: outcome price history
- AlphaDB backend API: optional normalized market reads via `ALPHADB_API_BASE_URL`

## Project Layout

```text
src/index.ts              App state, unified/single layout loop, input handling
src/api/provider.ts       Cross-provider fetch and chart interface
src/api/polymarket.ts     Gamma and CLOB adapters
src/api/kalshi.ts         Kalshi market discovery and history adapter
src/render/renderer.ts    ANSI layout, split view, and chart rendering
src/lib/fuzzy.ts          Local fuzzy ranking
src/lib/storage.ts        Persistent saved/recent state
src/lib/kalshiLive.ts     Optional authenticated Kalshi websocket ticker
../../docs/               Repo-wide decisions and plans
```

## Verification

```bash
npm run typecheck
npm run build
```
