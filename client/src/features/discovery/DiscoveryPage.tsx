import { useMemo, useState } from "react";

import { useDiscoveryPoller } from "./hooks/useDiscoveryPoller";
import type { StartDiscoveryRequest } from "./types";
import { DiscoveryErrorBanner } from "./components/DiscoveryErrorBanner";
import { DiscoveryLauncher } from "./components/DiscoveryLauncher";
import { ChannelsTable } from "./components/ChannelsTable";
import { RunStatusPanel } from "./components/RunStatusPanel";

export function DiscoveryPage(): JSX.Element {
  const {
    state,
    start,
    stop,
    refreshCurrentPage,
    goToPage,
    clearError,
  } = useDiscoveryPoller({
    autoRestore: true,
    pageSize: 10,
    pollIntervalMs: 900,
    pollIntervalMaxMs: 2500,
  });

  const [chainIdInput, setChainIdInput] = useState("137");
  const [wsUrlInput, setWsUrlInput] = useState("");

  const [formError, setFormError] = useState<string | null>(null);

  const isBusy = state.phase === "submitting" || state.phase === "polling";

  const canNextPage = !!(state.run && state.run.channels.page.hasMore);
  const canPrevPage = !!(state.run && state.run.channels.page.offset > 0);

  const nextOffset = useMemo(() => {
    if (!state.run) {
      return 0;
    }

    return state.run.channels.page.offset + state.run.channels.page.limit;
  }, [state.run]);

  const prevOffset = useMemo(() => {
    if (!state.run) {
      return 0;
    }

    return state.run.channels.page.offset - state.run.channels.page.limit;
  }, [state.run]);

  const handleStart = async () => {
    const parsedChainId = Number(chainIdInput);
    if (!Number.isInteger(parsedChainId) || parsedChainId <= 0) {
      setFormError("chainId must be a positive integer");
      return;
    }

    setFormError(null);
    clearError();

    const request: StartDiscoveryRequest = {
      chainId: parsedChainId,
      wsUrl: wsUrlInput.trim() || undefined,
    };

    await start(request);
  };

  return (
    <main className="app">
      <h1>Polymarket discovery</h1>

      <section className="card">
        <DiscoveryLauncher
          chainIdInput={chainIdInput}
          wsUrlInput={wsUrlInput}
          onChainIdChange={setChainIdInput}
          onWsUrlChange={setWsUrlInput}
          onStart={handleStart}
          onCancel={stop}
          disabled={false}
          busy={isBusy}
        />

        {formError ? <p className="field-error">{formError}</p> : null}
      </section>

      {state.phase === "error" && state.error ? <DiscoveryErrorBanner error={state.error} /> : null}

      <RunStatusPanel phase={state.phase} shell={state.shell} run={state.run} />

      <div className="card row actions-card">
        <button type="button" onClick={refreshCurrentPage} disabled={!state.shell}>
          Refresh current page
        </button>

        <button
          type="button"
          onClick={() => goToPage(prevOffset)}
          disabled={!canPrevPage}
        >
          Previous page
        </button>
        <button
          type="button"
          onClick={() => goToPage(nextOffset)}
          disabled={!canNextPage}
        >
          Next page
        </button>
      </div>

      <ChannelsTable
        model={state.run}
        onPrevious={canPrevPage ? () => goToPage(prevOffset) : undefined}
        onNext={canNextPage ? () => goToPage(nextOffset) : undefined}
      />

      <section className="card small-note">
        <h3>Run lifecycle</h3>
        <ul>
          <li>
            <strong>submitting</strong>: create/attach run on server
          </li>
          <li>
            <strong>polling</strong>: GET run endpoint with pagination until terminal
          </li>
          <li>
            <strong>completed</strong>: run finished successfully or partially
          </li>
          <li>
            <strong>failed</strong>: run completed with terminal failure
          </li>
          <li>
            <strong>error</strong>: transport / validation contract error
          </li>
        </ul>
        {state.run ? <p>Last known requestId: {state.run.run.requestId}</p> : null}
        {(state.phase === "completed" || state.phase === "failed") && state.run ? (
          <p>Terminal status: {state.run.run.status}</p>
        ) : null}
      </section>
    </main>
  );
}
