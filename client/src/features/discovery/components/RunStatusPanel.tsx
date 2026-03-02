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

function formatDateTime(value?: string): string {
  if (!value) {
    return "—";
  }

  return new Date(value).toLocaleString();
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
          {runData.source.enableOrderBook !== undefined ? (
            <div>
              <span>Enable order book</span>
              <strong>{String(runData.source.enableOrderBook)}</strong>
            </div>
          ) : null}

          {runData.source.notificationsEnabled !== undefined ? (
            <div>
              <span>Notifications enabled</span>
              <strong>{String(runData.source.notificationsEnabled)}</strong>
            </div>
          ) : null}

          {runData.source.negRisk !== undefined ? (
            <div>
              <span>Neg risk</span>
              <strong>{String(runData.source.negRisk)}</strong>
            </div>
          ) : null}

          {runData.source.minimumTickSizeMin !== undefined ? (
            <div>
              <span>Minimum tick size min</span>
              <strong>{runData.source.minimumTickSizeMin}</strong>
            </div>
          ) : null}

          {runData.source.minimumTickSizeMax !== undefined ? (
            <div>
              <span>Minimum tick size max</span>
              <strong>{runData.source.minimumTickSizeMax}</strong>
            </div>
          ) : null}

          {runData.source.makerBaseFeeMin !== undefined ? (
            <div>
              <span>Maker base fee min</span>
              <strong>{runData.source.makerBaseFeeMin}</strong>
            </div>
          ) : null}

          {runData.source.makerBaseFeeMax !== undefined ? (
            <div>
              <span>Maker base fee max</span>
              <strong>{runData.source.makerBaseFeeMax}</strong>
            </div>
          ) : null}

          {runData.source.takerBaseFeeMin !== undefined ? (
            <div>
              <span>Taker base fee min</span>
              <strong>{runData.source.takerBaseFeeMin}</strong>
            </div>
          ) : null}

          {runData.source.takerBaseFeeMax !== undefined ? (
            <div>
              <span>Taker base fee max</span>
              <strong>{runData.source.takerBaseFeeMax}</strong>
            </div>
          ) : null}

          {runData.source.secondsDelayMin !== undefined ? (
            <div>
              <span>Seconds delay min</span>
              <strong>{runData.source.secondsDelayMin}</strong>
            </div>
          ) : null}

          {runData.source.secondsDelayMax !== undefined ? (
            <div>
              <span>Seconds delay max</span>
              <strong>{runData.source.secondsDelayMax}</strong>
            </div>
          ) : null}

          {runData.source.acceptingOrderTimestampMin !== undefined ? (
            <div>
              <span>Accepting order ts min</span>
              <strong>{runData.source.acceptingOrderTimestampMin}</strong>
            </div>
          ) : null}

          {runData.source.acceptingOrderTimestampMax !== undefined ? (
            <div>
              <span>Accepting order ts max</span>
              <strong>{runData.source.acceptingOrderTimestampMax}</strong>
            </div>
          ) : null}

          {runData.source.endDateIsoMin ? (
            <div>
              <span>End date min</span>
              <strong>{formatDateTime(runData.source.endDateIsoMin)}</strong>
            </div>
          ) : null}

          {runData.source.endDateIsoMax ? (
            <div>
              <span>End date max</span>
              <strong>{formatDateTime(runData.source.endDateIsoMax)}</strong>
            </div>
          ) : null}

          {runData.source.gameStartTimeMin ? (
            <div>
              <span>Game start min</span>
              <strong>{formatDateTime(runData.source.gameStartTimeMin)}</strong>
            </div>
          ) : null}

          {runData.source.gameStartTimeMax ? (
            <div>
              <span>Game start max</span>
              <strong>{formatDateTime(runData.source.gameStartTimeMax)}</strong>
            </div>
          ) : null}

          {runData.source.descriptionContains ? (
            <div>
              <span>Description contains</span>
              <strong>{runData.source.descriptionContains}</strong>
            </div>
          ) : null}

          {runData.source.questionIdContains ? (
            <div>
              <span>Question ID contains</span>
              <strong>{runData.source.questionIdContains}</strong>
            </div>
          ) : null}

          {runData.source.rewardsHasRates !== undefined ? (
            <div>
              <span>Rewards has rates</span>
              <strong>{String(runData.source.rewardsHasRates)}</strong>
            </div>
          ) : null}

          {runData.source.rewardsMinSizeMin !== undefined ? (
            <div>
              <span>Rewards min size min</span>
              <strong>{runData.source.rewardsMinSizeMin}</strong>
            </div>
          ) : null}

          {runData.source.rewardsMinSizeMax !== undefined ? (
            <div>
              <span>Rewards min size max</span>
              <strong>{runData.source.rewardsMinSizeMax}</strong>
            </div>
          ) : null}

          {runData.source.rewardsMaxSpreadMin !== undefined ? (
            <div>
              <span>Rewards max spread min</span>
              <strong>{runData.source.rewardsMaxSpreadMin}</strong>
            </div>
          ) : null}

          {runData.source.rewardsMaxSpreadMax !== undefined ? (
            <div>
              <span>Rewards max spread max</span>
              <strong>{runData.source.rewardsMaxSpreadMax}</strong>
            </div>
          ) : null}

          {runData.source.iconContains ? (
            <div>
              <span>Icon contains</span>
              <strong>{runData.source.iconContains}</strong>
            </div>
          ) : null}

          {runData.source.imageContains ? (
            <div>
              <span>Image contains</span>
              <strong>{runData.source.imageContains}</strong>
            </div>
            ) : null}

          {runData.source.conditionIdContains ? (
            <div>
              <span>Condition ID contains</span>
              <strong>{runData.source.conditionIdContains}</strong>
            </div>
          ) : null}

          {runData.source.fpmm ? (
            <div>
              <span>FPMM</span>
              <strong>{runData.source.fpmm}</strong>
            </div>
          ) : null}

          {runData.source.negRiskMarketIdContains ? (
            <div>
              <span>Neg-risk market ID contains</span>
              <strong>{runData.source.negRiskMarketIdContains}</strong>
            </div>
          ) : null}

          {runData.source.negRiskRequestIdContains ? (
            <div>
              <span>Neg-risk request ID contains</span>
              <strong>{runData.source.negRiskRequestIdContains}</strong>
            </div>
          ) : null}

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

          {runData.source.active !== undefined ? (
            <div>
              <span>Active</span>
              <strong>{String(runData.source.active)}</strong>
            </div>
          ) : null}

          {runData.source.closed !== undefined ? (
            <div>
              <span>Closed</span>
              <strong>{String(runData.source.closed)}</strong>
            </div>
          ) : null}

          {runData.source.archived !== undefined ? (
            <div>
              <span>Archived</span>
              <strong>{String(runData.source.archived)}</strong>
            </div>
          ) : null}

          {runData.source.isFiftyFiftyOutcome !== undefined ? (
            <div>
              <span>50/50 outcome</span>
              <strong>{String(runData.source.isFiftyFiftyOutcome)}</strong>
            </div>
          ) : null}

          {runData.source.tags && runData.source.tags.length > 0 ? (
            <div>
              <span>Tags</span>
              <strong>{runData.source.tags.join(", ")}</strong>
            </div>
          ) : null}

          {runData.source.questionContains ? (
            <div>
              <span>Question contains</span>
              <strong>{runData.source.questionContains}</strong>
            </div>
          ) : null}

          {runData.source.marketSlugContains ? (
            <div>
              <span>Slug contains</span>
              <strong>{runData.source.marketSlugContains}</strong>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
