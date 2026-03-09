import { type DiscoveryApiError } from "../types";

interface DiscoveryErrorBannerProps {
  error: DiscoveryApiError;
}

export function DiscoveryErrorBanner({ error }: DiscoveryErrorBannerProps): JSX.Element {
  return (
    <section className="card error-card">
      <h3>Discovery failed</h3>
      <p>
        <strong>{error.error}</strong>
      </p>
      <ul>
        <li>
          <strong>Code:</strong> {error.code}
        </li>
        <li>
          <strong>Message:</strong> {error.message}
        </li>
        <li>
          <strong>Retryable:</strong> {error.retryable ? "Yes" : "No"}
        </li>
        <li>
          <strong>Request ID:</strong> {error.requestId}
        </li>
      </ul>
      {error.details ? <pre>{JSON.stringify(error.details, null, 2)}</pre> : null}
    </section>
  );
}
