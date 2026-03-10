import { startTransition, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { applyLiveUpdate, buildSubscriptions, clampIndex, createClient, defaultProviderState, displayMarketsForMode, loadLocalPersistentState, loadStoredToken, persistLocalState, persistToken, PROVIDERS, RANGE_ORDER, touchRecentState, toggleSavedState, updatePersistentStateMarkets, } from "./shared";
export function useMarketWorkspace() {
    const [apiTokenDraft, setApiTokenDraft] = useState(() => loadStoredToken());
    const [apiToken, setApiToken] = useState(() => loadStoredToken());
    const [authStatus, setAuthStatus] = useState(null);
    const [workspace, setWorkspace] = useState({
        trending: { polymarket: [], kalshi: [] },
        search: { polymarket: [], kalshi: [] },
        persistent: loadLocalPersistentState(),
    });
    const [viewMode, setViewMode] = useState("trending");
    const [focusedProvider, setFocusedProvider] = useState("polymarket");
    const [statusMessage, setStatusMessage] = useState("Loading unified workspace…");
    const [errorMessage, setErrorMessage] = useState("");
    const [loadingMarkets, setLoadingMarkets] = useState(true);
    const [range, setRange] = useState("24h");
    const [lastMarketRefreshAt, setLastMarketRefreshAt] = useState(null);
    const [providerState, setProviderState] = useState({
        polymarket: defaultProviderState("polymarket"),
        kalshi: defaultProviderState("kalshi"),
    });
    const [backendStateEnabled, setBackendStateEnabled] = useState(false);
    const [query, setQuery] = useState("");
    const searchInputRef = useRef(null);
    const deferredSearchQuery = useDeferredValue(query);
    const displayedMarkets = useMemo(() => ({
        polymarket: displayMarketsForMode(viewMode, "polymarket", workspace),
        kalshi: displayMarketsForMode(viewMode, "kalshi", workspace),
    }), [viewMode, workspace]);
    const selectedMarkets = useMemo(() => ({
        polymarket: displayedMarkets.polymarket[clampIndex(providerState.polymarket.selectedIndex, displayedMarkets.polymarket.length)] ?? null,
        kalshi: displayedMarkets.kalshi[clampIndex(providerState.kalshi.selectedIndex, displayedMarkets.kalshi.length)] ?? null,
    }), [displayedMarkets, providerState]);
    const savedIds = useMemo(() => new Set(workspace.persistent.savedMarkets.map((entry) => entry.market.id)), [workspace.persistent.savedMarkets]);
    const recentIds = useMemo(() => new Set(workspace.persistent.recentMarkets.map((entry) => entry.market.id)), [workspace.persistent.recentMarkets]);
    useEffect(() => {
        persistLocalState(workspace.persistent);
    }, [workspace.persistent]);
    useEffect(() => {
        persistToken(apiToken);
    }, [apiToken]);
    useEffect(() => {
        setProviderState((current) => ({
            polymarket: {
                ...current.polymarket,
                selectedIndex: clampIndex(current.polymarket.selectedIndex, displayedMarkets.polymarket.length),
            },
            kalshi: {
                ...current.kalshi,
                selectedIndex: clampIndex(current.kalshi.selectedIndex, displayedMarkets.kalshi.length),
            },
        }));
    }, [displayedMarkets.kalshi.length, displayedMarkets.polymarket.length]);
    useEffect(() => {
        let cancelled = false;
        async function bootstrapAuth() {
            const client = createClient(apiToken);
            try {
                const nextAuthStatus = await client.fetchAuthStatus();
                if (cancelled) {
                    return;
                }
                startTransition(() => {
                    setAuthStatus(nextAuthStatus);
                    setStatusMessage(nextAuthStatus.enabled
                        ? nextAuthStatus.viewer
                            ? `Authenticated as ${nextAuthStatus.viewer.userId}`
                            : "Backend auth required for saved state"
                        : "Backend auth disabled");
                });
                if (!nextAuthStatus.enabled || nextAuthStatus.viewer) {
                    const remoteState = await client.fetchPersistentState();
                    if (cancelled) {
                        return;
                    }
                    startTransition(() => {
                        setWorkspace((current) => ({
                            ...current,
                            persistent: remoteState,
                        }));
                        setBackendStateEnabled(true);
                    });
                    return;
                }
                startTransition(() => {
                    setBackendStateEnabled(false);
                    setWorkspace((current) => ({
                        ...current,
                        persistent: loadLocalPersistentState(),
                    }));
                });
            }
            catch (error) {
                if (cancelled) {
                    return;
                }
                startTransition(() => {
                    setAuthStatus(null);
                    setBackendStateEnabled(false);
                    setWorkspace((current) => ({
                        ...current,
                        persistent: loadLocalPersistentState(),
                    }));
                    setErrorMessage(error instanceof Error ? error.message : "Failed to check backend auth.");
                });
            }
        }
        void bootstrapAuth();
        return () => {
            cancelled = true;
        };
    }, [apiToken]);
    const refreshAll = () => {
        setLoadingMarkets(true);
        setErrorMessage("");
        void createClient(apiToken)
            .fetchUnifiedTrendingMarkets(14)
            .then((markets) => {
            startTransition(() => {
                setWorkspace((current) => ({ ...current, trending: markets }));
                setLastMarketRefreshAt(Date.now());
                setLoadingMarkets(false);
                if (viewMode === "trending") {
                    setStatusMessage("Unified market workspace loaded.");
                }
            });
        })
            .catch((error) => {
            startTransition(() => {
                setLoadingMarkets(false);
                setErrorMessage(error instanceof Error ? error.message : "Failed to load unified markets.");
            });
        });
    };
    useEffect(() => {
        refreshAll();
    }, [apiToken]);
    useEffect(() => {
        const trimmed = deferredSearchQuery.trim();
        if (!trimmed) {
            if (viewMode === "search") {
                setViewMode("trending");
            }
            return;
        }
        let cancelled = false;
        async function loadSearch() {
            setLoadingMarkets(true);
            setErrorMessage("");
            try {
                const client = createClient(apiToken);
                const results = await client.fetchUnifiedSearchMarkets(trimmed, 12);
                if (cancelled) {
                    return;
                }
                startTransition(() => {
                    setWorkspace((current) => ({ ...current, search: results }));
                    setViewMode("search");
                    setLoadingMarkets(false);
                    setStatusMessage(`Search results for "${trimmed}"`);
                });
            }
            catch (error) {
                if (cancelled) {
                    return;
                }
                startTransition(() => {
                    setLoadingMarkets(false);
                    setErrorMessage(error instanceof Error ? error.message : "Failed to search markets.");
                });
            }
        }
        void loadSearch();
        return () => {
            cancelled = true;
        };
    }, [apiToken, deferredSearchQuery, viewMode]);
    useEffect(() => {
        const client = createClient(apiToken);
        const stream = client.createMarketStream({
            onStatus: (status) => {
                startTransition(() => {
                    setProviderState((current) => ({
                        ...current,
                        [status.provider]: {
                            ...current[status.provider],
                            liveStatusMessage: status.message,
                        },
                    }));
                });
            },
            onUpdate: (update) => {
                startTransition(() => {
                    setWorkspace((current) => ({
                        trending: {
                            polymarket: current.trending.polymarket.map((market) => market.id === update.marketId ? applyLiveUpdate(market, update) : market),
                            kalshi: current.trending.kalshi.map((market) => market.id === update.marketId ? applyLiveUpdate(market, update) : market),
                        },
                        search: {
                            polymarket: current.search.polymarket.map((market) => market.id === update.marketId ? applyLiveUpdate(market, update) : market),
                            kalshi: current.search.kalshi.map((market) => market.id === update.marketId ? applyLiveUpdate(market, update) : market),
                        },
                        persistent: updatePersistentStateMarkets(current.persistent, update.marketId, (market) => applyLiveUpdate(market, update)),
                    }));
                });
            },
        });
        stream.replaceSubscriptions(buildSubscriptions(displayedMarkets));
        return () => {
            stream.close();
        };
    }, [apiToken, displayedMarkets]);
    useEffect(() => {
        const disposers = [];
        for (const provider of PROVIDERS) {
            const market = selectedMarkets[provider];
            if (!market) {
                startTransition(() => {
                    setProviderState((current) => ({
                        ...current,
                        [provider]: {
                            ...current[provider],
                            chartPoints: [],
                            loadingChart: false,
                        },
                    }));
                });
                continue;
            }
            let cancelled = false;
            disposers.push(() => {
                cancelled = true;
            });
            startTransition(() => {
                setProviderState((current) => ({
                    ...current,
                    [provider]: {
                        ...current[provider],
                        loadingChart: true,
                    },
                }));
            });
            void createClient(apiToken)
                .fetchMarketHistory(market, range)
                .then((points) => {
                if (cancelled) {
                    return;
                }
                startTransition(() => {
                    setProviderState((current) => ({
                        ...current,
                        [provider]: {
                            ...current[provider],
                            chartPoints: points,
                            loadingChart: false,
                            lastChartRefreshAt: Date.now(),
                        },
                    }));
                    setWorkspace((current) => ({
                        ...current,
                        persistent: touchRecentState(current.persistent, market),
                    }));
                });
                if (backendStateEnabled) {
                    void createClient(apiToken)
                        .touchRecentMarket(market)
                        .then((remoteState) => {
                        startTransition(() => {
                            setWorkspace((current) => ({ ...current, persistent: remoteState }));
                        });
                    })
                        .catch(() => undefined);
                }
            })
                .catch((error) => {
                if (cancelled) {
                    return;
                }
                startTransition(() => {
                    setProviderState((current) => ({
                        ...current,
                        [provider]: {
                            ...current[provider],
                            chartPoints: [],
                            loadingChart: false,
                        },
                    }));
                    setErrorMessage(error instanceof Error ? error.message : `Failed to load ${provider} chart.`);
                });
            });
        }
        return () => {
            for (const dispose of disposers) {
                dispose();
            }
        };
    }, [apiToken, backendStateEnabled, range, selectedMarkets.kalshi, selectedMarkets.polymarket]);
    useEffect(() => {
        const handleKeyDown = (event) => {
            if (event.metaKey || event.ctrlKey || event.altKey) {
                return;
            }
            const target = event.target;
            const editing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
            if (event.key === "/") {
                event.preventDefault();
                searchInputRef.current?.focus();
                return;
            }
            if (editing && event.key !== "Escape") {
                return;
            }
            if (event.key === "h" || event.key === "ArrowLeft") {
                event.preventDefault();
                setFocusedProvider("polymarket");
                return;
            }
            if (event.key === "l" || event.key === "ArrowRight") {
                event.preventDefault();
                setFocusedProvider("kalshi");
                return;
            }
            if (event.key === "1") {
                event.preventDefault();
                setFocusedProvider("polymarket");
                return;
            }
            if (event.key === "2") {
                event.preventDefault();
                setFocusedProvider("kalshi");
                return;
            }
            if (event.key === "3") {
                event.preventDefault();
                setViewMode("trending");
                setQuery("");
                setStatusMessage("Unified market workspace reset.");
                return;
            }
            if (event.key === "j" || event.key === "ArrowDown") {
                event.preventDefault();
                setProviderState((current) => ({
                    ...current,
                    [focusedProvider]: {
                        ...current[focusedProvider],
                        selectedIndex: clampIndex(current[focusedProvider].selectedIndex + 1, displayedMarkets[focusedProvider].length),
                    },
                }));
                return;
            }
            if (event.key === "k" || event.key === "ArrowUp") {
                event.preventDefault();
                setProviderState((current) => ({
                    ...current,
                    [focusedProvider]: {
                        ...current[focusedProvider],
                        selectedIndex: clampIndex(current[focusedProvider].selectedIndex - 1, displayedMarkets[focusedProvider].length),
                    },
                }));
                return;
            }
            if (event.key === "[") {
                event.preventDefault();
                setRange((current) => RANGE_ORDER[Math.max(RANGE_ORDER.indexOf(current) - 1, 0)]);
                return;
            }
            if (event.key === "]") {
                event.preventDefault();
                setRange((current) => RANGE_ORDER[Math.min(RANGE_ORDER.indexOf(current) + 1, RANGE_ORDER.length - 1)]);
                return;
            }
            if (event.key === "f") {
                event.preventDefault();
                const market = selectedMarkets[focusedProvider];
                if (!market) {
                    return;
                }
                const result = toggleSavedState(workspace.persistent, market);
                startTransition(() => {
                    setWorkspace((current) => ({
                        ...current,
                        persistent: result.state,
                    }));
                    setStatusMessage(result.saved ? `Saved ${market.question}` : `Removed ${market.question}`);
                });
                if (backendStateEnabled) {
                    const client = createClient(apiToken);
                    const sync = result.saved ? client.saveMarket(market) : client.removeSavedMarket(market.id);
                    void sync.then((remoteState) => {
                        startTransition(() => {
                            setWorkspace((current) => ({ ...current, persistent: remoteState }));
                        });
                    }).catch(() => undefined);
                }
                return;
            }
            if (event.key === "r") {
                event.preventDefault();
                refreshAll();
            }
        };
        window.addEventListener("keydown", handleKeyDown);
        return () => {
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [apiToken, backendStateEnabled, displayedMarkets, focusedProvider, selectedMarkets, workspace.persistent]);
    const applyApiToken = () => {
        setApiToken(apiTokenDraft.trim());
        setErrorMessage("");
    };
    const selectMarket = (provider, index) => {
        setFocusedProvider(provider);
        setProviderState((current) => ({
            ...current,
            [provider]: {
                ...current[provider],
                selectedIndex: index,
            },
        }));
    };
    const toggleSaveFocusedMarket = () => {
        const market = selectedMarkets[focusedProvider];
        if (!market) {
            return;
        }
        const result = toggleSavedState(workspace.persistent, market);
        startTransition(() => {
            setWorkspace((current) => ({
                ...current,
                persistent: result.state,
            }));
            setStatusMessage(result.saved ? `Saved ${market.question}` : `Removed ${market.question}`);
        });
        if (backendStateEnabled) {
            const client = createClient(apiToken);
            const sync = result.saved ? client.saveMarket(market) : client.removeSavedMarket(market.id);
            void sync.then((remoteState) => {
                startTransition(() => {
                    setWorkspace((current) => ({ ...current, persistent: remoteState }));
                });
            }).catch(() => undefined);
        }
    };
    return {
        apiTokenDraft,
        setApiTokenDraft,
        applyApiToken,
        authStatus,
        backendStateEnabled,
        query,
        setQuery,
        searchInputRef,
        viewMode,
        setViewMode,
        focusedProvider,
        setFocusedProvider,
        statusMessage,
        errorMessage,
        loadingMarkets,
        range,
        setRange,
        lastMarketRefreshAt,
        providerState,
        displayedMarkets,
        selectedMarkets,
        savedIds,
        recentIds,
        selectMarket,
        toggleSaveFocusedMarket,
        refreshAll,
    };
}
