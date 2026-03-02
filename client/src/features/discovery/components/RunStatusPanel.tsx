import type { DiscoveryRunReadModel, DiscoveryRunShell, DiscoveryPhase } from "../types";

function statusLabel(phase: DiscoveryPhase, status?: string): string {
  switch (phase) {
    case "submitting":
      return "Submitting";
    case "polling":
      return status || "Polling";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "error":
      return "Error";
    default:
      return "Ready";
  }
}

interface RunStatusPanelProps {
  phase: DiscoveryPhase;
  shell?: DiscoveryRunShell;
  run?: DiscoveryRunReadModel;
}

export function RunStatusPanel({ phase, shell, run }: RunStatusPanelProps): JSX.Element {
  const runData = run?.run;

  const statusText = statusLabel(phase, shell?.status);

  return (
    <div className="status-panel">
      <h2>{statusText}</h2>

      {phase === "idle" ? <p>Configure and start a discovery run.</p> : null}

      {shell ? (
        <div className="kv-grid">
          <div>
            <span>Run ID</span>
            <strong>{shell.runId}</strong>
          </div>
          <div>
            <span>Request ID</span>
            <strong>{shell.requestId}</strong>
          </div>
          <div>
            <span>Status</span>
            <strong>{shell.status}</strong>
          </div>
        </div>
      ) : null}

      {runData ? (
        <div className="kv-grid">
          <div>
            <span>Source</span>
            <strong>{runData.source.clobApiUrl}</strong>
          </div>
          <div>
            <span>Chain</span>
            <strong>{runData.source.chainId}</strong>
          </div>
          <div>
            <span>Market count</span>
            <strong>{runData.marketCount}</strong>
          </div>
          <div>
            <span>Channel count</span>
            <strong>{runData.marketChannelCount}</strong>
          </div>
          <div>
            <span>Requested at</span>
            <strong>{new Date(runData.requestedAt).toLocaleString()}</strong>
          </div>
          {runData.startedAt ? (
            <div>
              <span>Started at</span>
              <strong>{new Date(runData.startedAt).toLocaleString()}</strong>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
