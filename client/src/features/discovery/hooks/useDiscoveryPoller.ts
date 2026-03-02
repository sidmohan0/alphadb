import { useCallback, useEffect, useRef, useState } from "react";

import { pollDiscoveryRun, startDiscoveryRun } from "../api/discoveryApi";
import {
  type DiscoveryApiError,
  type DiscoveryHookConfig,
  type DiscoveryHookState,
  type DiscoveryPersistedShell,
  type DiscoveryPollResult,
  type DiscoveryRunReadModel,
  type DiscoveryRunShell,
  type DiscoveryPhase,
  type StartDiscoveryRequest,
} from "../types";

const DEFAULT_PAGE_SIZE = 20;
const DEFAULT_OPTIONS = {
  pageSize: DEFAULT_PAGE_SIZE,
  autoRestore: false,
  storageKey: "alphadb.discovery.polling.shell",
  pollIntervalMs: 750,
  pollIntervalMaxMs: 3000,
  pollBackoffFactor: 1.45,
  maxPollAttempts: 300,
};

const POLLING_PHASES: DiscoveryPhase[] = ["submitting", "polling"];

function isDiscoveryApiError(value: unknown): value is DiscoveryApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { error?: unknown }).error === "string" &&
    typeof (value as { code?: unknown }).code === "string" &&
    typeof (value as { message?: unknown }).message === "string" &&
    typeof (value as { requestId?: unknown }).requestId === "string"
  );
}

function fallbackError(message: string): DiscoveryApiError {
  return {
    error: "Discovery request failed",
    code: "unexpected_error",
    message,
    retryable: false,
    requestId: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
  };
}

function derivePhaseFromRun(run: DiscoveryRunReadModel): DiscoveryPhase {
  switch (run.run.status) {
    case "queued":
    case "running":
      return "polling";
    case "failed":
      return "failed";
    case "succeeded":
    case "partial":
      return "completed";
    default:
      return "error";
  }
}

function computeDelay(attempt: number, baseMs: number, maxMs: number, factor: number): number {
  if (attempt <= 1) {
    return Math.min(baseMs, maxMs);
  }

  return Math.min(Math.floor(baseMs * Math.pow(factor, attempt - 1)), maxMs);
}

function readStoredShell(storageKey: string): DiscoveryPersistedShell | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(storageKey);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw);

    if (
      parsed &&
      typeof parsed === "object" &&
      typeof parsed.pollUrl === "string" &&
      typeof parsed.runId === "string" &&
      typeof parsed.requestId === "string"
    ) {
      return {
        pollUrl: parsed.pollUrl,
        runId: parsed.runId,
        requestId: parsed.requestId,
        createdAt: parsed.createdAt || "",
      };
    }

    return null;
  } catch {
    return null;
  }
}

function writeStoredShell(storageKey: string, shell: DiscoveryRunShell | null): void {
  if (typeof window === "undefined") {
    return;
  }

  if (!shell) {
    window.localStorage.removeItem(storageKey);
    return;
  }

  const payload: DiscoveryPersistedShell = {
    pollUrl: shell.pollUrl,
    runId: shell.runId,
    requestId: shell.requestId,
    createdAt: new Date().toISOString(),
  };

  window.localStorage.setItem(storageKey, JSON.stringify(payload));
}

export function useDiscoveryPoller(userOptions: DiscoveryHookConfig = {}): {
  state: DiscoveryHookState;
  start: (request: StartDiscoveryRequest) => Promise<void>;
  stop: () => void;
  refreshCurrentPage: () => void;
  goToPage: (offset: number) => void;
  clearError: () => void;
  setPollIntervalOverride: (enabled: boolean) => void;
} {
  const options: Required<DiscoveryHookConfig> = {
    pageSize: userOptions.pageSize ?? DEFAULT_OPTIONS.pageSize,
    autoRestore: userOptions.autoRestore ?? DEFAULT_OPTIONS.autoRestore,
    storageKey: userOptions.storageKey ?? DEFAULT_OPTIONS.storageKey,
    pollIntervalMs: userOptions.pollIntervalMs ?? DEFAULT_OPTIONS.pollIntervalMs,
    pollIntervalMaxMs: userOptions.pollIntervalMaxMs ?? DEFAULT_OPTIONS.pollIntervalMaxMs,
    pollBackoffFactor: userOptions.pollBackoffFactor ?? DEFAULT_OPTIONS.pollBackoffFactor,
    maxPollAttempts: userOptions.maxPollAttempts ?? DEFAULT_OPTIONS.maxPollAttempts,
  };

  const [state, setState] = useState<DiscoveryHookState>({
    phase: "idle",
    offset: 0,
    pollAttempt: 0,
  });

  const stateRef = useRef(state);
  const pollingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const [fastPollMode, setFastPollMode] = useState(false);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const clearPollTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const abortActiveRequest = useCallback(() => {
    if (requestRef.current) {
      requestRef.current.abort();
      requestRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    pollingRef.current = false;
    clearPollTimer();
    abortActiveRequest();
    writeStoredShell(options.storageKey, null);

    if (POLLING_PHASES.includes(stateRef.current.phase)) {
      setState((prev) => ({
        ...prev,
        phase: "idle",
      }));
    }
  }, [abortActiveRequest, clearPollTimer, options.storageKey]);

  const schedulePoll = useCallback(
    (attempt: number) => {
      const delay = computeDelay(
        attempt,
        fastPollMode ? options.pollIntervalMs / 2 : options.pollIntervalMs,
        options.pollIntervalMaxMs,
        options.pollBackoffFactor
      );

      clearPollTimer();
      timerRef.current = setTimeout(() => {
        void pollCurrent({ force: false });
      }, delay);
    },
    [clearPollTimer, fastPollMode, options.pollBackoffFactor, options.pollIntervalMaxMs, options.pollIntervalMs]
  );

  const pollCurrent = useCallback(
    async (opts?: {
      force?: boolean;
      shell?: DiscoveryRunShell;
      offset?: number;
    }): Promise<void> => {
      const force = opts?.force === true;
      const current = stateRef.current;
      const allowPolling = force || pollingRef.current;
      const shell = opts?.shell ?? current.shell;
      const requestOffset = opts?.offset ?? current.offset;

      if (!allowPolling || !shell?.pollUrl) {
        return;
      }

      const attempt = current.pollAttempt + 1;
      const activeRequest = new AbortController();
      requestRef.current = activeRequest;

      let result: DiscoveryPollResult;
      try {
        result = await pollDiscoveryRun(
          shell.pollUrl,
          requestOffset,
          options.pageSize,
          activeRequest.signal
        );
      } catch (error) {
        if ((error as { name?: string }).name === "AbortError") {
          return;
        }

        const mapped =
          isDiscoveryApiError(error) ? error : fallbackError("Failed to poll discovery run");

        setState((prev) => ({
          ...prev,
          phase: "error",
          error: mapped,
        }));
        pollingRef.current = false;
        writeStoredShell(options.storageKey, null);
        return;
      } finally {
        requestRef.current = null;
      }

      if (result.kind === "shell") {
        setState((prev) => {
          const nextAttempt = prev.pollAttempt + 1;
          return {
            ...prev,
            phase: "polling",
            shell: result.shell,
            pollAttempt: nextAttempt,
            error: undefined,
          };
        });
        writeStoredShell(options.storageKey, result.shell);

        if (attempt >= options.maxPollAttempts) {
          setState((prev) => ({
            ...prev,
            phase: "error",
            error: {
              ...fallbackError("Polling timed out. Run appears to be taking longer than expected."),
              code: "discovery_timeout",
              retryable: true,
            },
          }));
          pollingRef.current = false;
          writeStoredShell(options.storageKey, null);
          return;
        }

        schedulePoll(attempt);
        return;
      }

      if (result.kind === "run") {
        const phase = derivePhaseFromRun(result.run);
        const keepPolling = phase === "polling";

        setState((prev) => ({
          ...prev,
          phase,
          run: result.run,
          shell: prev.shell,
          pollAttempt: 0,
          error: undefined,
        }));

        if (keepPolling) {
          pollingRef.current = true;
          schedulePoll(1);
          return;
        }

        pollingRef.current = false;
        writeStoredShell(options.storageKey, null);
        return;
      }

      setState((prev) => ({
        ...prev,
        phase: "error",
        error: result.error,
      }));
      pollingRef.current = false;
      writeStoredShell(options.storageKey, null);
    },
    [options.maxPollAttempts, options.pageSize, options.storageKey, schedulePoll]
  );

  const start = useCallback(
    async (request: StartDiscoveryRequest): Promise<void> => {
      if (stateRef.current.phase === "submitting") {
        return;
      }

      stop();
      setState((prev) => ({
        ...prev,
        phase: "submitting",
        offset: 0,
        run: undefined,
        error: undefined,
      }));

      const controller = new AbortController();
      requestRef.current = controller;

      try {
        const shell = await startDiscoveryRun(request, controller.signal);
        requestRef.current = null;

        setState((prev) => ({
          ...prev,
          phase: "polling",
          shell,
          offset: 0,
          pollAttempt: 0,
          error: undefined,
        }));

        writeStoredShell(options.storageKey, shell);
        pollingRef.current = true;
        await pollCurrent({ force: true, shell });
      } catch (error) {
        requestRef.current = null;

        const mapped =
          isDiscoveryApiError(error) ? error : fallbackError("Failed to start discovery");

        setState((prev) => ({
          ...prev,
          phase: "error",
          error: mapped,
        }));
      }
    },
    [options.storageKey, pollCurrent, stop]
  );

  const refreshCurrentPage = useCallback(() => {
    void pollCurrent({
      force: true,
      shell: stateRef.current.shell,
      offset: stateRef.current.offset,
    });
  }, [pollCurrent]);

  const goToPage = useCallback(
    (offset: number) => {
      const sanitizedOffset = Math.max(0, Math.floor(offset));
      setState((prev) => ({
        ...prev,
        offset: sanitizedOffset,
      }));
      pollCurrent({
        force: true,
        shell: stateRef.current.shell,
        offset: sanitizedOffset,
      });
    },
    [pollCurrent]
  );

  const clearError = useCallback(() => {
    setState((prev) => ({
      ...prev,
      error: undefined,
    }));
  }, []);

  const setPollIntervalOverride = useCallback(
    (enabled: boolean) => {
      setFastPollMode(enabled);
    },
    []
  );

  useEffect(() => {
    if (!options.autoRestore) {
      return;
    }

    const persisted = readStoredShell(options.storageKey);
    if (!persisted) {
      return;
    }

    if (!persisted.pollUrl || !persisted.runId) {
      writeStoredShell(options.storageKey, null);
      return;
    }

    const shell: DiscoveryRunShell = {
      pollUrl: persisted.pollUrl,
      runId: persisted.runId,
      status: "queued",
      requestId: persisted.requestId,
    };

    pollingRef.current = true;
    setState((prev) => ({
      ...prev,
      phase: "polling",
      shell,
      offset: 0,
      pollAttempt: 0,
      error: undefined,
    }));

    void pollCurrent({ force: true, shell });
  }, [options.autoRestore, options.storageKey, pollCurrent]);

  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  return {
    state,
    start,
    stop,
    refreshCurrentPage,
    goToPage,
    clearError,
    setPollIntervalOverride,
  };
}
