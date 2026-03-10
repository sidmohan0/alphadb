import type { CSSProperties } from "react";

import { ChartPanel } from "./components/ChartPanel";
import { MarketDetail } from "./components/MarketDetail";
import { MarketTable } from "./components/MarketTable";
import { formatAge, providerThemes, PROVIDERS } from "./shared";
import { useMarketWorkspace } from "./useMarketWorkspace";

export function MarketWorkspacePage() {
  const workspace = useMarketWorkspace();
  const focusedMarket = workspace.selectedMarkets[workspace.focusedProvider];

  return (
    <main className="workspace-shell">
      <header className="top-bar">
        <div className="top-title">
          <span className="brand-block">AlphaDB</span>
          <span className="brand-subtitle">Markets Web</span>
          <span className="mode-pill">Unified Mode · Focus {providerThemes[workspace.focusedProvider].label}</span>
        </div>
        <div className="top-meta">
          <span>markets {formatAge(workspace.lastMarketRefreshAt)}</span>
          <span>chart {formatAge(workspace.providerState[workspace.focusedProvider].lastChartRefreshAt)}</span>
        </div>
      </header>

      <div className="headline">
        {focusedMarket?.question ?? "Prediction-market workspace"}
      </div>

      <section className="command-row">
        <div className="provider-switches">
          {PROVIDERS.map((provider) => (
            <button
              key={provider}
              type="button"
              className={`command-button ${workspace.focusedProvider === provider ? "active" : ""}`}
              onClick={() => workspace.setFocusedProvider(provider)}
            >
              {providerThemes[provider].label}
            </button>
          ))}
        </div>
        <div className="view-switches">
          {(["trending", "saved", "recent"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              className={`command-button ${workspace.viewMode === mode ? "active" : ""}`}
              onClick={() => workspace.setViewMode(mode)}
            >
              {mode}
            </button>
          ))}
        </div>
        <label className="search-block">
          <span>Search</span>
          <input
            ref={workspace.searchInputRef}
            value={workspace.query}
            onChange={(event) => workspace.setQuery(event.target.value)}
            placeholder="Search both providers"
          />
        </label>
        <label className="token-block">
          <span>API Token</span>
          <div className="token-row">
            <input
              value={workspace.apiTokenDraft}
              onChange={(event) => workspace.setApiTokenDraft(event.target.value)}
              placeholder="Optional bearer token"
            />
            <button
              type="button"
              className="command-button active"
              onClick={workspace.applyApiToken}
            >
              Apply
            </button>
          </div>
        </label>
      </section>

      {workspace.authStatus?.enabled && !workspace.authStatus.viewer ? (
        <section className="status-banner warning-banner">
          Backend auth is enabled. Market reads still work, but saved and recent state stay local until you provide `ALPHADB_API_TOKEN`.
        </section>
      ) : null}

      {workspace.errorMessage ? <section className="status-banner error-banner">{workspace.errorMessage}</section> : null}

      <section className="workspace-grid">
        {PROVIDERS.map((provider) => {
          const selectedMarket = workspace.selectedMarkets[provider];
          const theme = providerThemes[provider];
          const shellStyle = {
            "--provider-border": theme.border,
            "--provider-border-soft": theme.borderSoft,
            "--provider-panel": theme.panel,
            "--provider-text": theme.text,
            "--provider-selected": theme.selected,
          } as CSSProperties;

          return (
            <div
              key={provider}
              className={`provider-column ${workspace.focusedProvider === provider ? "focused-column" : ""}`}
              style={shellStyle}
            >
              <div className="provider-heading">
                <span>{theme.label}</span>
                <span className="provider-side">{provider === "polymarket" ? "left" : "right"}</span>
              </div>

              <MarketTable
                provider={provider}
                markets={workspace.displayedMarkets[provider]}
                selectedIndex={workspace.providerState[provider].selectedIndex}
                focused={workspace.focusedProvider === provider}
                savedIds={workspace.savedIds}
                recentIds={workspace.recentIds}
                onSelect={(index) => workspace.selectMarket(provider, index)}
              />

              <ChartPanel
                provider={provider}
                points={workspace.providerState[provider].chartPoints}
                loading={workspace.providerState[provider].loadingChart}
              />

              <MarketDetail
                provider={provider}
                market={selectedMarket}
                liveStatus={workspace.providerState[provider].liveStatusMessage}
                saved={selectedMarket ? workspace.savedIds.has(selectedMarket.id) : false}
              />
            </div>
          );
        })}
      </section>

      <footer className="footer-bar">
        <div className="footer-hints">
          <span>1 polymarket</span>
          <span>2 kalshi</span>
          <span>3 reset</span>
          <span>h/l focus</span>
          <span>j/k move</span>
          <span>[ ] range</span>
          <span>f save</span>
          <span>/ search</span>
        </div>
        <div className="footer-status">
          {workspace.loadingMarkets ? "Loading markets…" : workspace.statusMessage}
        </div>
      </footer>
    </main>
  );
}
