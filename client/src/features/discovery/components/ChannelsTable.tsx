import type { DiscoveryPhase, DiscoveryRunReadModel } from "../types";

interface ChannelsTableProps {
  model?: DiscoveryRunReadModel;
  phase: DiscoveryPhase;
  onPrevious?: () => void;
  onNext?: () => void;
}

export function ChannelsTable({
  model,
  phase,
  onPrevious,
  onNext,
}: ChannelsTableProps): JSX.Element {
  if (!model) {
    return (
      <section className="card">
        <h3>Discovered channels</h3>
        <p>No run data loaded yet.</p>
      </section>
    );
  }

  const { channels } = model;
  const isScanning = phase === "submitting" || phase === "polling";

  return (
    <section className="card">
      <h3>Discovered channels</h3>
      <p>
        {channels.page.total === 0
          ? "No channels discovered yet for the current scan window."
          : `Showing ${channels.page.offset + 1} - ${channels.page.offset + channels.items.length} of ${channels.page.total}`}
      </p>

      <div className="channels-shell">
        <table>
          <thead>
            <tr>
              <th>Asset</th>
              <th>Condition</th>
              <th>Question</th>
              <th>Outcome</th>
              <th>Slug</th>
            </tr>
          </thead>
          <tbody>
            {channels.items.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  {isScanning
                    ? "Discovery is still running. No channels found for this page yet."
                    : "No channels found for this page."}
                </td>
              </tr>
            ) : (
              channels.items.map((row) => (
                <tr key={row.assetId}>
                  <td>{row.assetId}</td>
                  <td>{row.conditionId || "-"}</td>
                  <td>{row.question || "-"}</td>
                  <td>{row.outcome || "-"}</td>
                  <td>{row.marketSlug || "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination">
        <button type="button" onClick={onPrevious} disabled={!onPrevious || channels.page.offset === 0}>
          Previous
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!onNext || !channels.page.hasMore}
        >
          Next
        </button>
      </div>
    </section>
  );
}
