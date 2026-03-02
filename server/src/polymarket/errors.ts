import { randomUUID } from "crypto";

type ErrorCode =
  | "invalid_input"
  | "clob_request_timeout"
  | "clob_request_network"
  | "clob_request_failure"
  | "websocket_invalid_url"
  | "websocket_request_error"
  | "unexpected_error";

export type DiscoveryErrorCode = ErrorCode;

export interface DiscoveryErrorDetails {
  component?: "clob" | "websocket" | "controller";
  operation?: string;
  requestId?: string;
  [key: string]: unknown;
}

export interface DiscoveryErrorResponse {
  error: string;
  code: ErrorCode;
  message: string;
  retryable: boolean;
  details: DiscoveryErrorDetails;
  requestId: string;
}

export interface DiscoveryHttpError {
  status: number;
  body: DiscoveryErrorResponse;
}

interface UnknownErrorRecord {
  code?: unknown;
  status?: unknown;
  statusCode?: unknown;
  message?: unknown;
  response?: unknown;
}

type ErrorRecord = UnknownErrorRecord & Record<string, unknown>;

function isRecord(value: unknown): value is ErrorRecord {
  return Boolean(value && typeof value === "object");
}

function toRequestId(requestId?: string): string {
  return requestId || randomUUID();
}

const RETRYABLE_NODE_CODES = new Set([
  "ETIMEDOUT",
  "ECONNRESET",
  "ECONNREFUSED",
  "ENOTFOUND",
  "EAI_AGAIN",
  "ECONNABORTED",
  "EHOSTUNREACH",
]);

export class PolymarketDiscoveryError extends Error {
  code: ErrorCode;
  status: number;
  retryable: boolean;
  details: DiscoveryErrorDetails;

  constructor(
    message: string,
    code: ErrorCode,
    status: number,
    retryable: boolean,
    details: DiscoveryErrorDetails = {}
  ) {
    super(message);
    this.name = "PolymarketDiscoveryError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
    this.details = details;
  }
}

function formatResponse(error: PolymarketDiscoveryError, requestId: string): DiscoveryHttpError {
  return {
    status: error.status,
    body: {
      error: "Failed to discover market channels",
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      details: {
        ...error.details,
        component: error.details.component,
        operation: error.details.operation,
      },
      requestId,
    },
  };
}

function extractErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  if (isRecord(error) && typeof error.message === "string") {
    return error.message;
  }

  return "Unexpected failure";
}

function getHttpStatus(error: ErrorRecord): number | undefined {
  const fromError = typeof error.status === "number" ? error.status : undefined;
  if (fromError) {
    return fromError;
  }

  const fromStatusCode = typeof error.statusCode === "number" ? error.statusCode : undefined;
  if (fromStatusCode) {
    return fromStatusCode;
  }

  if (isRecord(error.response)) {
    const responseStatus = error.response.status;
    if (typeof responseStatus === "number") {
      return responseStatus;
    }

    const responseStatusCode = (error.response as ErrorRecord).statusCode;
    if (typeof responseStatusCode === "number") {
      return responseStatusCode;
    }
  }

  return undefined;
}

function isRetryableNetworkCode(error: ErrorRecord): boolean {
  const code = error.code;
  return typeof code === "string" && RETRYABLE_NODE_CODES.has(code);
}

function toHttpError(error: PolymarketDiscoveryError, requestId: string): DiscoveryHttpError {
  return formatResponse(error, requestId);
}

export function toHttpErrorResponse(error: unknown, requestId?: string): DiscoveryHttpError {
  const requestIdSafe = toRequestId(requestId);

  if (error instanceof PolymarketDiscoveryError) {
    return toHttpError(error, requestIdSafe);
  }

  const record: ErrorRecord = isRecord(error) ? error : {};
  const status = getHttpStatus(record);
  const message = extractErrorMessage(error);

  if (status === 400) {
    return toHttpError(
      new PolymarketDiscoveryError("Invalid request parameter", "invalid_input", 400, false, {
        component: "controller",
        message,
      }),
      requestIdSafe
    );
  }

  if (status === 429) {
    return toHttpError(
      new PolymarketDiscoveryError("Rate limit exceeded", "clob_request_failure", 429, true, {
        component: "clob",
        status,
      }),
      requestIdSafe
    );
  }

  if (status && status >= 500) {
    return toHttpError(
      new PolymarketDiscoveryError(
        `Upstream service responded with status ${status}`,
        "clob_request_failure",
        502,
        true,
        {
          component: "clob",
          status,
        }
      ),
      requestIdSafe
    );
  }

  if (isRetryableNetworkCode(record)) {
    return toHttpError(
      new PolymarketDiscoveryError(`Clob network failure (${String(record.code)})`, "clob_request_network", 502, true, {
        component: "clob",
        code: String(record.code),
      }),
      requestIdSafe
    );
  }

  if (message.toLowerCase().includes("timeout")) {
    return toHttpError(
      new PolymarketDiscoveryError("Clob request timed out", "clob_request_timeout", 504, true, {
        component: "clob",
        message,
      }),
      requestIdSafe
    );
  }

  return toHttpError(
    new PolymarketDiscoveryError("Unexpected failure", "unexpected_error", 500, false, {
      component: "clob",
      message,
    }),
    requestIdSafe
  );
}

export function mapClobRequestFailure(error: unknown, context: DiscoveryErrorDetails = {}): PolymarketDiscoveryError {
  const record: ErrorRecord = isRecord(error) ? error : {};
  const status = getHttpStatus(record);

  if (status === 429) {
    return new PolymarketDiscoveryError("Clob request rate limit reached", "clob_request_failure", 429, true, {
      ...context,
      component: "clob",
      status,
    });
  }

  if (status && status >= 500) {
    return new PolymarketDiscoveryError(`Clob request failed with status ${status}`, "clob_request_failure", 502, true, {
      ...context,
      component: "clob",
      status,
    });
  }

  if (isRetryableNetworkCode(record)) {
    return new PolymarketDiscoveryError(`Clob network failure (${String(record.code)})`, "clob_request_network", 502, true, {
      ...context,
      component: "clob",
      code: String(record.code),
    });
  }

  const message = extractErrorMessage(error);
  if (message.toLowerCase().includes("timeout")) {
    return new PolymarketDiscoveryError("Clob request timed out", "clob_request_timeout", 504, true, {
      ...context,
      component: "clob",
      message,
    });
  }

  return new PolymarketDiscoveryError(message, "unexpected_error", 500, false, {
    ...context,
    component: "clob",
  });
}

export function mapWebsocketInvalidUrl(message: string): PolymarketDiscoveryError {
  return new PolymarketDiscoveryError(message, "websocket_invalid_url", 400, false, {
    component: "websocket",
    message,
  });
}

export function mapWebsocketFailure(message: string): PolymarketDiscoveryError {
  return new PolymarketDiscoveryError(message, "websocket_request_error", 502, false, {
    component: "websocket",
    message,
  });
}

export function mapInvalidInput(message: string, field: string): PolymarketDiscoveryError {
  return new PolymarketDiscoveryError(message, "invalid_input", 400, false, {
    component: "controller",
    field,
    message,
  });
}
