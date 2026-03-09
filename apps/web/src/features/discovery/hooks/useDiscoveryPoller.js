import { useCallback, useEffect, useRef, useState } from "react";
import { pollDiscoveryRun, startDiscoveryRun } from "../api/discoveryApi";
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
const POLLING_PHASES = ["submitting", "polling"];
function isDiscoveryApiError(value) {
    return (typeof value === "object" &&
        value !== null &&
        typeof value.error === "string" &&
        typeof value.code === "string" &&
        typeof value.message === "string" &&
        typeof value.requestId === "string");
}
function fallbackError(message) {
    return {
        error: "Discovery request failed",
        code: "unexpected_error",
        message,
        retryable: false,
        requestId: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    };
}
function derivePhaseFromRun(run) {
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
function computeDelay(attempt, baseMs, maxMs, factor) {
    if (attempt <= 1) {
        return Math.min(baseMs, maxMs);
    }
    return Math.min(Math.floor(baseMs * Math.pow(factor, attempt - 1)), maxMs);
}
function readStoredShell(storageKey) {
    if (typeof window === "undefined") {
        return null;
    }
    try {
        const raw = window.localStorage.getItem(storageKey);
        if (!raw) {
            return null;
        }
        const parsed = JSON.parse(raw);
        if (parsed &&
            typeof parsed === "object" &&
            typeof parsed.pollUrl === "string" &&
            typeof parsed.runId === "string" &&
            typeof parsed.requestId === "string") {
            return {
                pollUrl: parsed.pollUrl,
                runId: parsed.runId,
                requestId: parsed.requestId,
                createdAt: parsed.createdAt || "",
            };
        }
        return null;
    }
    catch {
        return null;
    }
}
function writeStoredShell(storageKey, shell) {
    if (typeof window === "undefined") {
        return;
    }
    try {
        if (!shell) {
            window.localStorage.removeItem(storageKey);
            return;
        }
        const payload = {
            pollUrl: shell.pollUrl,
            runId: shell.runId,
            requestId: shell.requestId,
            createdAt: new Date().toISOString(),
        };
        window.localStorage.setItem(storageKey, JSON.stringify(payload));
    }
    catch {
        // Incognito/private mode or storage restrictions should not hard-fail discovery.
    }
}
export function useDiscoveryPoller(userOptions = {}) {
    const options = {
        pageSize: userOptions.pageSize ?? DEFAULT_OPTIONS.pageSize,
        autoRestore: userOptions.autoRestore ?? DEFAULT_OPTIONS.autoRestore,
        storageKey: userOptions.storageKey ?? DEFAULT_OPTIONS.storageKey,
        pollIntervalMs: userOptions.pollIntervalMs ?? DEFAULT_OPTIONS.pollIntervalMs,
        pollIntervalMaxMs: userOptions.pollIntervalMaxMs ?? DEFAULT_OPTIONS.pollIntervalMaxMs,
        pollBackoffFactor: userOptions.pollBackoffFactor ?? DEFAULT_OPTIONS.pollBackoffFactor,
        maxPollAttempts: userOptions.maxPollAttempts ?? DEFAULT_OPTIONS.maxPollAttempts,
    };
    const [state, setState] = useState({
        phase: "idle",
        offset: 0,
        pollAttempt: 0,
    });
    const stateRef = useRef(state);
    const pollingRef = useRef(false);
    const timerRef = useRef(null);
    const requestRef = useRef(null);
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
    const schedulePoll = useCallback((attempt) => {
        const delay = computeDelay(attempt, fastPollMode ? options.pollIntervalMs / 2 : options.pollIntervalMs, options.pollIntervalMaxMs, options.pollBackoffFactor);
        clearPollTimer();
        timerRef.current = setTimeout(() => {
            void pollCurrent({ force: false });
        }, delay);
    }, [clearPollTimer, fastPollMode, options.pollBackoffFactor, options.pollIntervalMaxMs, options.pollIntervalMs]);
    const pollCurrent = useCallback(async (opts) => {
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
        let result;
        try {
            result = await pollDiscoveryRun(shell.pollUrl, requestOffset, options.pageSize, activeRequest.signal);
        }
        catch (error) {
            if (error.name === "AbortError") {
                return;
            }
            const mapped = isDiscoveryApiError(error) ? error : fallbackError("Failed to poll discovery run");
            setState((prev) => ({
                ...prev,
                phase: "error",
                error: mapped,
            }));
            pollingRef.current = false;
            writeStoredShell(options.storageKey, null);
            return;
        }
        finally {
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
    }, [options.maxPollAttempts, options.pageSize, options.storageKey, schedulePoll]);
    const start = useCallback(async (request) => {
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
        }
        catch (error) {
            requestRef.current = null;
            const mapped = isDiscoveryApiError(error) ? error : fallbackError("Failed to start discovery");
            setState((prev) => ({
                ...prev,
                phase: "error",
                error: mapped,
            }));
        }
    }, [options.storageKey, pollCurrent, stop]);
    const refreshCurrentPage = useCallback(() => {
        void pollCurrent({
            force: true,
            shell: stateRef.current.shell,
            offset: stateRef.current.offset,
        });
    }, [pollCurrent]);
    const goToPage = useCallback((offset) => {
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
    }, [pollCurrent]);
    const clearError = useCallback(() => {
        setState((prev) => ({
            ...prev,
            error: undefined,
        }));
    }, []);
    const setPollIntervalOverride = useCallback((enabled) => {
        setFastPollMode(enabled);
    }, []);
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
        const shell = {
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
