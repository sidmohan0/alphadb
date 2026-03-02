import type {
  DiscoveryApiError,
  DiscoveryPollResult,
  DiscoveryPollResultError,
  DiscoveryPollResultRun,
  DiscoveryPollResultShell,
  DiscoveryRunReadModel,
  DiscoveryRunShell,
  StartDiscoveryRequest,
} from "../types";

async function parseJsonResponse<T>(response: Response, fallbackErrorMessage: string): Promise<T> {
  try {
    const text = await response.text();
    if (!text.trim()) {
      throw new Error(fallbackErrorMessage);
    }

    return JSON.parse(text) as T;
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error(fallbackErrorMessage);
    }

    throw error;
  }
}

function isDiscoveryApiError(value: unknown): value is DiscoveryApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    "code" in value &&
    "message" in value &&
    "requestId" in value
  );
}

function makeRequestIdFallback(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export async function startDiscoveryRun(
  request: StartDiscoveryRequest,
  signal?: AbortSignal
): Promise<DiscoveryRunShell> {
  const response = await fetch("/api/polymarket/market-channels/runs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    const payload = await parseJsonResponse<DiscoveryApiError>(
      response,
      "Discovery start request returned an invalid error payload"
    );

    if (!isDiscoveryApiError(payload)) {
      throw new Error("Discovery run start failed");
    }

    throw payload;
  }

  const payload = await parseJsonResponse<DiscoveryRunShell>(
    response,
    "Discovery start request returned an invalid response"
  );

  return payload;
}

export async function pollDiscoveryRun(
  pollUrl: string,
  offset: number,
  limit: number,
  signal?: AbortSignal
): Promise<DiscoveryPollResult> {
  const target = new URL(pollUrl, window.location.origin);
  target.searchParams.set("offset", String(offset));
  target.searchParams.set("limit", String(limit));

  const response = await fetch(target.toString(), { signal });

  if (response.status === 202) {
    const shell = await parseJsonResponse<DiscoveryRunShell>(
      response,
      "Discovery poll returned an invalid shell payload"
    );
    const result: DiscoveryPollResultShell = {
      kind: "shell",
      status: response.status,
      shell,
    };
    return result;
  }

  if (response.status === 200) {
    const run = await parseJsonResponse<DiscoveryRunReadModel>(
      response,
      "Discovery poll returned an invalid run payload"
    );
    const result: DiscoveryPollResultRun = {
      kind: "run",
      status: response.status,
      run,
    };
    return result;
  }

  const fallbackError = await parseJsonResponse<DiscoveryApiError>(
    response,
    "Discovery poll returned an unexpected non-JSON error"
  );

  const error: DiscoveryApiError = isDiscoveryApiError(fallbackError)
    ? fallbackError
    : {
        error: "Unexpected discovery error",
        code: "unexpected_error",
        message: "Failed to poll discovery run",
        retryable: false,
        details: { status: response.status },
        requestId: makeRequestIdFallback(),
      };

  const result: DiscoveryPollResultError = {
    kind: "error",
    status: response.status,
    error,
  };

  return result;
}
