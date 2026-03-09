import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { cancelDiscoveryRun, estimateDiscoveryRun, listActiveDiscoveryRuns } from "./api/discoveryApi";
import { useDiscoveryPoller } from "./hooks/useDiscoveryPoller";
import { DiscoveryErrorBanner } from "./components/DiscoveryErrorBanner";
import { DiscoveryLauncher } from "./components/DiscoveryLauncher";
import { ChannelsTable } from "./components/ChannelsTable";
import { RunStatusPanel } from "./components/RunStatusPanel";
function isDiscoveryApiError(value) {
    return (typeof value === "object" &&
        value !== null &&
        typeof value.error === "string" &&
        typeof value.code === "string" &&
        typeof value.message === "string" &&
        typeof value.requestId === "string");
}
function formatDate(value) {
    if (!value) {
        return "—";
    }
    return new Date(value).toLocaleString();
}
function parseNonNegativeInput(value, fieldLabel) {
    const normalized = value.trim();
    if (!normalized) {
        return undefined;
    }
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed) || parsed < 0) {
        throw new Error(`${fieldLabel} must be a non-negative number`);
    }
    return parsed;
}
function parsePositiveIntInput(value, fieldLabel) {
    const normalized = value.trim();
    if (!normalized) {
        return undefined;
    }
    const parsed = Number(normalized);
    if (!Number.isInteger(parsed) || parsed <= 0) {
        throw new Error(`${fieldLabel} must be a positive integer`);
    }
    return parsed;
}
function parseDateTimeInput(value, fieldLabel) {
    const normalized = value.trim();
    if (!normalized) {
        return undefined;
    }
    const parsed = Date.parse(normalized);
    if (!Number.isFinite(parsed)) {
        throw new Error(`${fieldLabel} must be a valid date-time`);
    }
    return new Date(parsed).toISOString();
}
function toLocalDateTimeInput(value) {
    const parsed = Date.parse(value);
    if (!Number.isFinite(parsed)) {
        return "";
    }
    const date = new Date(parsed);
    const pad = (number) => number.toString().padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
export function DiscoveryPage() {
    const { state, start, stop, refreshCurrentPage, goToPage, clearError, } = useDiscoveryPoller({
        autoRestore: true,
        pageSize: 10,
        pollIntervalMs: 900,
        pollIntervalMaxMs: 2500,
    });
    const [chainIdInput, setChainIdInput] = useState("137");
    const [clobApiUrlInput, setClobApiUrlInput] = useState("");
    const [wsUrlInput, setWsUrlInput] = useState("");
    const [wsConnectTimeoutMsInput, setWsConnectTimeoutMsInput] = useState("");
    const [wsChunkSizeInput, setWsChunkSizeInput] = useState("");
    const [marketFetchTimeoutMsInput, setMarketFetchTimeoutMsInput] = useState("");
    const [maxMarketsInput, setMaxMarketsInput] = useState("");
    const [activeFilter, setActiveFilter] = useState(false);
    const [closedFilter, setClosedFilter] = useState(false);
    const [archivedFilter, setArchivedFilter] = useState(false);
    const [isFiftyFiftyOutcomeFilter, setIsFiftyFiftyOutcomeFilter] = useState(false);
    const [acceptingOrdersFilter, setAcceptingOrdersFilter] = useState(false);
    const [enableOrderBookFilter, setEnableOrderBookFilter] = useState(false);
    const [notificationsEnabledFilter, setNotificationsEnabledFilter] = useState(false);
    const [negRiskFilter, setNegRiskFilter] = useState(false);
    const [minimumOrderSizeMinInput, setMinimumOrderSizeMinInput] = useState("");
    const [minimumOrderSizeMaxInput, setMinimumOrderSizeMaxInput] = useState("");
    const [minimumTickSizeMinInput, setMinimumTickSizeMinInput] = useState("");
    const [minimumTickSizeMaxInput, setMinimumTickSizeMaxInput] = useState("");
    const [makerBaseFeeMinInput, setMakerBaseFeeMinInput] = useState("");
    const [makerBaseFeeMaxInput, setMakerBaseFeeMaxInput] = useState("");
    const [takerBaseFeeMinInput, setTakerBaseFeeMinInput] = useState("");
    const [takerBaseFeeMaxInput, setTakerBaseFeeMaxInput] = useState("");
    const [secondsDelayMinInput, setSecondsDelayMinInput] = useState("");
    const [secondsDelayMaxInput, setSecondsDelayMaxInput] = useState("");
    const [acceptingOrderTimestampMinInput, setAcceptingOrderTimestampMinInput] = useState("");
    const [acceptingOrderTimestampMaxInput, setAcceptingOrderTimestampMaxInput] = useState("");
    const [endDateIsoMinInput, setEndDateIsoMinInput] = useState("");
    const [endDateIsoMaxInput, setEndDateIsoMaxInput] = useState("");
    const [gameStartTimeMinInput, setGameStartTimeMinInput] = useState("");
    const [gameStartTimeMaxInput, setGameStartTimeMaxInput] = useState("");
    const [descriptionContainsInput, setDescriptionContainsInput] = useState("");
    const [conditionIdContainsInput, setConditionIdContainsInput] = useState("");
    const [fpmmContainsInput, setFpmmContainsInput] = useState("");
    const [negRiskMarketIdContainsInput, setNegRiskMarketIdContainsInput] = useState("");
    const [negRiskRequestIdContainsInput, setNegRiskRequestIdContainsInput] = useState("");
    const [questionIdContainsInput, setQuestionIdContainsInput] = useState("");
    const [rewardsHasRatesFilter, setRewardsHasRatesFilter] = useState(false);
    const [rewardsMinSizeMinInput, setRewardsMinSizeMinInput] = useState("");
    const [rewardsMinSizeMaxInput, setRewardsMinSizeMaxInput] = useState("");
    const [rewardsMaxSpreadMinInput, setRewardsMaxSpreadMinInput] = useState("");
    const [rewardsMaxSpreadMaxInput, setRewardsMaxSpreadMaxInput] = useState("");
    const [iconContainsInput, setIconContainsInput] = useState("");
    const [imageContainsInput, setImageContainsInput] = useState("");
    const [tagsInput, setTagsInput] = useState("");
    const [questionContainsInput, setQuestionContainsInput] = useState("");
    const [marketSlugContainsInput, setMarketSlugContainsInput] = useState("");
    const [presetInput, setPresetInput] = useState("");
    const [presetError, setPresetError] = useState(null);
    const [formError, setFormError] = useState(null);
    const [activeRuns, setActiveRuns] = useState([]);
    const [activeRunsError, setActiveRunsError] = useState(null);
    const [cancelingRunIds, setCancelingRunIds] = useState(new Set());
    const [previewResult, setPreviewResult] = useState(null);
    const [previewError, setPreviewError] = useState(null);
    const [previewing, setPreviewing] = useState(false);
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
    const loadActiveRuns = async (signal) => {
        try {
            const payload = await listActiveDiscoveryRuns(signal);
            setActiveRuns(payload.runs);
            setActiveRunsError(null);
        }
        catch (error) {
            if (error.name === "AbortError") {
                return;
            }
            setActiveRunsError(isDiscoveryApiError(error)
                ? error
                : {
                    error: "Discovery request failed",
                    code: "unexpected_error",
                    message: "Failed to fetch active discovery jobs",
                    retryable: false,
                    requestId: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
                });
        }
    };
    const handleCancelRun = async (runId) => {
        setCancelingRunIds((current) => {
            const next = new Set(current);
            next.add(runId);
            return next;
        });
        try {
            await cancelDiscoveryRun(runId);
            setActiveRunsError(null);
            await loadActiveRuns();
        }
        catch (error) {
            setActiveRunsError(isDiscoveryApiError(error)
                ? error
                : {
                    error: "Discovery request failed",
                    code: "unexpected_error",
                    message: "Failed to cancel discovery run",
                    retryable: false,
                    requestId: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
                });
        }
        finally {
            setCancelingRunIds((current) => {
                const next = new Set(current);
                next.delete(runId);
                return next;
            });
        }
    };
    const parsePresetBoolean = (value, fieldLabel) => {
        if (value === undefined || value === null) {
            return false;
        }
        if (typeof value !== "boolean") {
            throw new Error(`${fieldLabel} must be a boolean`);
        }
        return value;
    };
    const parsePresetString = (value, fieldLabel) => {
        if (value === undefined || value === null) {
            return "";
        }
        if (typeof value !== "string") {
            throw new Error(`${fieldLabel} must be a string`);
        }
        return value.trim();
    };
    const parsePresetNumber = (value, fieldLabel) => {
        if (value === undefined || value === null) {
            return "";
        }
        const stringValue = typeof value === "number" ? value.toString() : String(value).trim();
        if (!stringValue) {
            return "";
        }
        const parsed = Number(stringValue);
        if (!Number.isFinite(parsed) || parsed < 0) {
            throw new Error(`${fieldLabel} must be a non-negative number`);
        }
        return stringValue;
    };
    const parsePresetPositiveInt = (value, fieldLabel) => {
        if (value === undefined || value === null) {
            return "";
        }
        const parsed = typeof value === "number" ? value : Number(String(value).trim());
        if (!Number.isInteger(parsed) || parsed <= 0) {
            throw new Error(`${fieldLabel} must be a positive integer`);
        }
        return parsed.toString();
    };
    const parsePresetDateTime = (value, fieldLabel) => {
        if (value === undefined || value === null) {
            return "";
        }
        if (typeof value !== "string") {
            throw new Error(`${fieldLabel} must be an ISO date-time string`);
        }
        if (!Number.isFinite(Date.parse(value))) {
            throw new Error(`${fieldLabel} must be a valid date-time`);
        }
        return toLocalDateTimeInput(value);
    };
    const parsePresetTags = (value) => {
        if (value === undefined || value === null) {
            return "";
        }
        if (Array.isArray(value)) {
            const tags = value
                .map((item) => {
                if (typeof item !== "string") {
                    throw new Error("tags must be an array of strings");
                }
                return item.trim();
            })
                .filter((item) => item.length > 0);
            return tags.join(", ");
        }
        if (typeof value === "string") {
            return value;
        }
        throw new Error("tags must be comma-separated string or array of strings");
    };
    const buildDiscoveryRequest = () => {
        const parsedChainId = Number(chainIdInput);
        if (!Number.isInteger(parsedChainId) || parsedChainId <= 0) {
            throw new Error("chainId must be a positive integer");
        }
        const request = {
            chainId: parsedChainId,
            wsUrl: wsUrlInput.trim() || undefined,
        };
        const clobApiUrlValue = clobApiUrlInput.trim();
        if (clobApiUrlValue) {
            request.clobApiUrl = clobApiUrlValue;
        }
        request.wsConnectTimeoutMs = parsePositiveIntInput(wsConnectTimeoutMsInput, "wsConnectTimeoutMs");
        request.wsChunkSize = parsePositiveIntInput(wsChunkSizeInput, "wsChunkSize");
        request.marketFetchTimeoutMs = parsePositiveIntInput(marketFetchTimeoutMsInput, "marketFetchTimeoutMs");
        request.maxMarkets = parsePositiveIntInput(maxMarketsInput, "maxMarkets");
        if (activeFilter) {
            request.active = true;
        }
        if (closedFilter) {
            request.closed = true;
        }
        if (archivedFilter) {
            request.archived = true;
        }
        if (isFiftyFiftyOutcomeFilter) {
            request.isFiftyFiftyOutcome = true;
        }
        if (acceptingOrdersFilter) {
            request.acceptingOrders = true;
        }
        if (enableOrderBookFilter) {
            request.enableOrderBook = true;
        }
        if (notificationsEnabledFilter) {
            request.notificationsEnabled = true;
        }
        if (negRiskFilter) {
            request.negRisk = true;
        }
        request.minimumOrderSizeMin = parseNonNegativeInput(minimumOrderSizeMinInput, "minimumOrderSizeMin");
        request.minimumOrderSizeMax = parseNonNegativeInput(minimumOrderSizeMaxInput, "minimumOrderSizeMax");
        if (!validateRange(request.minimumOrderSizeMin, request.minimumOrderSizeMax, "minimumOrderSizeMax must be >= minimumOrderSizeMin")) {
            throw new Error("minimumOrderSizeMax must be >= minimumOrderSizeMin");
        }
        request.minimumTickSizeMin = parseNonNegativeInput(minimumTickSizeMinInput, "minimumTickSizeMin");
        request.minimumTickSizeMax = parseNonNegativeInput(minimumTickSizeMaxInput, "minimumTickSizeMax");
        if (!validateRange(request.minimumTickSizeMin, request.minimumTickSizeMax, "minimumTickSizeMax must be >= minimumTickSizeMin")) {
            throw new Error("minimumTickSizeMax must be >= minimumTickSizeMin");
        }
        request.makerBaseFeeMin = parseNonNegativeInput(makerBaseFeeMinInput, "makerBaseFeeMin");
        request.makerBaseFeeMax = parseNonNegativeInput(makerBaseFeeMaxInput, "makerBaseFeeMax");
        if (!validateRange(request.makerBaseFeeMin, request.makerBaseFeeMax, "makerBaseFeeMax must be >= makerBaseFeeMin")) {
            throw new Error("makerBaseFeeMax must be >= makerBaseFeeMin");
        }
        request.takerBaseFeeMin = parseNonNegativeInput(takerBaseFeeMinInput, "takerBaseFeeMin");
        request.takerBaseFeeMax = parseNonNegativeInput(takerBaseFeeMaxInput, "takerBaseFeeMax");
        if (!validateRange(request.takerBaseFeeMin, request.takerBaseFeeMax, "takerBaseFeeMax must be >= takerBaseFeeMin")) {
            throw new Error("takerBaseFeeMax must be >= takerBaseFeeMin");
        }
        request.rewardsMinSizeMin = parseNonNegativeInput(rewardsMinSizeMinInput, "rewardsMinSizeMin");
        request.rewardsMinSizeMax = parseNonNegativeInput(rewardsMinSizeMaxInput, "rewardsMinSizeMax");
        if (!validateRange(request.rewardsMinSizeMin, request.rewardsMinSizeMax, "rewardsMinSizeMax must be >= rewardsMinSizeMin")) {
            throw new Error("rewardsMinSizeMax must be >= rewardsMinSizeMin");
        }
        request.rewardsMaxSpreadMin = parseNonNegativeInput(rewardsMaxSpreadMinInput, "rewardsMaxSpreadMin");
        request.rewardsMaxSpreadMax = parseNonNegativeInput(rewardsMaxSpreadMaxInput, "rewardsMaxSpreadMax");
        if (!validateRange(request.rewardsMaxSpreadMin, request.rewardsMaxSpreadMax, "rewardsMaxSpreadMax must be >= rewardsMaxSpreadMin")) {
            throw new Error("rewardsMaxSpreadMax must be >= rewardsMaxSpreadMin");
        }
        if (rewardsHasRatesFilter) {
            request.rewardsHasRates = true;
        }
        request.secondsDelayMin = parseNonNegativeInput(secondsDelayMinInput, "secondsDelayMin");
        request.secondsDelayMax = parseNonNegativeInput(secondsDelayMaxInput, "secondsDelayMax");
        if (!validateRange(request.secondsDelayMin, request.secondsDelayMax, "secondsDelayMax must be >= secondsDelayMin")) {
            throw new Error("secondsDelayMax must be >= secondsDelayMin");
        }
        request.acceptingOrderTimestampMin = parseNonNegativeInput(acceptingOrderTimestampMinInput, "acceptingOrderTimestampMin");
        request.acceptingOrderTimestampMax = parseNonNegativeInput(acceptingOrderTimestampMaxInput, "acceptingOrderTimestampMax");
        if (!validateRange(request.acceptingOrderTimestampMin, request.acceptingOrderTimestampMax, "acceptingOrderTimestampMax must be >= acceptingOrderTimestampMin")) {
            throw new Error("acceptingOrderTimestampMax must be >= acceptingOrderTimestampMin");
        }
        request.endDateIsoMin = parseDateTimeInput(endDateIsoMinInput, "endDateIsoMin");
        request.endDateIsoMax = parseDateTimeInput(endDateIsoMaxInput, "endDateIsoMax");
        if (request.endDateIsoMin !== undefined &&
            request.endDateIsoMax !== undefined &&
            Date.parse(request.endDateIsoMax) < Date.parse(request.endDateIsoMin)) {
            throw new Error("endDateIsoMax must be >= endDateIsoMin");
        }
        request.gameStartTimeMin = parseDateTimeInput(gameStartTimeMinInput, "gameStartTimeMin");
        request.gameStartTimeMax = parseDateTimeInput(gameStartTimeMaxInput, "gameStartTimeMax");
        if (request.gameStartTimeMin !== undefined &&
            request.gameStartTimeMax !== undefined &&
            Date.parse(request.gameStartTimeMax) < Date.parse(request.gameStartTimeMin)) {
            throw new Error("gameStartTimeMax must be >= gameStartTimeMin");
        }
        const tags = tagsInput
            .split(",")
            .map((tag) => tag.trim())
            .filter((tag) => tag.length > 0);
        if (tags.length > 0) {
            request.tags = tags;
        }
        const questionContains = questionContainsInput.trim();
        if (questionContains) {
            request.questionContains = questionContains;
        }
        const marketSlugContains = marketSlugContainsInput.trim();
        if (marketSlugContains) {
            request.marketSlugContains = marketSlugContains;
        }
        const descriptionContains = descriptionContainsInput.trim();
        if (descriptionContains) {
            request.descriptionContains = descriptionContains;
        }
        const conditionIdContains = conditionIdContainsInput.trim();
        if (conditionIdContains) {
            request.conditionIdContains = conditionIdContains;
        }
        const fpmmContains = fpmmContainsInput.trim();
        if (fpmmContains) {
            request.fpmm = fpmmContains;
        }
        const negRiskMarketIdContains = negRiskMarketIdContainsInput.trim();
        if (negRiskMarketIdContains) {
            request.negRiskMarketIdContains = negRiskMarketIdContains;
        }
        const negRiskRequestIdContains = negRiskRequestIdContainsInput.trim();
        if (negRiskRequestIdContains) {
            request.negRiskRequestIdContains = negRiskRequestIdContains;
        }
        const questionIdContains = questionIdContainsInput.trim();
        if (questionIdContains) {
            request.questionIdContains = questionIdContains;
        }
        const iconContains = iconContainsInput.trim();
        if (iconContains) {
            request.iconContains = iconContains;
        }
        const imageContains = imageContainsInput.trim();
        if (imageContains) {
            request.imageContains = imageContains;
        }
        return request;
    };
    const handlePresetCopy = async () => {
        try {
            const request = buildDiscoveryRequest();
            const nextPreset = JSON.stringify(request, null, 2);
            setPresetInput(nextPreset);
            setPresetError(null);
            if (typeof navigator === "undefined" || typeof navigator.clipboard?.writeText !== "function") {
                throw new Error("Clipboard API is unavailable in this browser context");
            }
            await navigator.clipboard.writeText(nextPreset);
        }
        catch (error) {
            setPresetError(error instanceof Error ? error.message : "Failed to copy preset");
        }
    };
    const handlePresetLoad = () => {
        try {
            setPresetError(null);
            const parsed = JSON.parse(presetInput);
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
                throw new Error("Preset must be a JSON object");
            }
            const preset = parsed;
            const toOptionalNumber = (value) => (value ? Number(value) : undefined);
            const toOptionalString = (value) => (value ? value : undefined);
            const chainIdValue = preset.chainId !== undefined
                ? typeof preset.chainId === "number"
                    ? preset.chainId
                    : Number(preset.chainId)
                : Number(chainIdInput);
            if (!Number.isInteger(chainIdValue) || chainIdValue <= 0) {
                throw new Error("chainId must be a positive integer");
            }
            const wsUrlValue = parsePresetString(preset.wsUrl, "wsUrl");
            const clobApiUrlValue = parsePresetString(preset.clobApiUrl, "clobApiUrl");
            const wsConnectTimeoutMs = parsePresetPositiveInt(preset.wsConnectTimeoutMs, "wsConnectTimeoutMs");
            const wsChunkSize = parsePresetPositiveInt(preset.wsChunkSize, "wsChunkSize");
            const marketFetchTimeoutMs = parsePresetPositiveInt(preset.marketFetchTimeoutMs, "marketFetchTimeoutMs");
            const maxMarkets = parsePresetPositiveInt(preset.maxMarkets, "maxMarkets");
            const minimumOrderSizeMin = parsePresetNumber(preset.minimumOrderSizeMin, "minimumOrderSizeMin");
            const minimumOrderSizeMax = parsePresetNumber(preset.minimumOrderSizeMax, "minimumOrderSizeMax");
            const minimumTickSizeMin = parsePresetNumber(preset.minimumTickSizeMin, "minimumTickSizeMin");
            const minimumTickSizeMax = parsePresetNumber(preset.minimumTickSizeMax, "minimumTickSizeMax");
            const makerBaseFeeMin = parsePresetNumber(preset.makerBaseFeeMin, "makerBaseFeeMin");
            const makerBaseFeeMax = parsePresetNumber(preset.makerBaseFeeMax, "makerBaseFeeMax");
            const takerBaseFeeMin = parsePresetNumber(preset.takerBaseFeeMin, "takerBaseFeeMin");
            const takerBaseFeeMax = parsePresetNumber(preset.takerBaseFeeMax, "takerBaseFeeMax");
            const secondsDelayMin = parsePresetNumber(preset.secondsDelayMin, "secondsDelayMin");
            const secondsDelayMax = parsePresetNumber(preset.secondsDelayMax, "secondsDelayMax");
            const acceptingOrderTimestampMin = parsePresetNumber(preset.acceptingOrderTimestampMin, "acceptingOrderTimestampMin");
            const acceptingOrderTimestampMax = parsePresetNumber(preset.acceptingOrderTimestampMax, "acceptingOrderTimestampMax");
            const rewardsMinSizeMin = parsePresetNumber(preset.rewardsMinSizeMin, "rewardsMinSizeMin");
            const rewardsMinSizeMax = parsePresetNumber(preset.rewardsMinSizeMax, "rewardsMinSizeMax");
            const rewardsMaxSpreadMin = parsePresetNumber(preset.rewardsMaxSpreadMin, "rewardsMaxSpreadMin");
            const rewardsMaxSpreadMax = parsePresetNumber(preset.rewardsMaxSpreadMax, "rewardsMaxSpreadMax");
            const endDateIsoMin = parsePresetDateTime(preset.endDateIsoMin, "endDateIsoMin");
            const endDateIsoMax = parsePresetDateTime(preset.endDateIsoMax, "endDateIsoMax");
            const gameStartTimeMin = parsePresetDateTime(preset.gameStartTimeMin, "gameStartTimeMin");
            const gameStartTimeMax = parsePresetDateTime(preset.gameStartTimeMax, "gameStartTimeMax");
            const descriptionContains = parsePresetString(preset.descriptionContains, "descriptionContains");
            const conditionIdContains = parsePresetString(preset.conditionIdContains, "conditionIdContains");
            const fpmmContains = parsePresetString(preset.fpmm, "fpmm");
            const negRiskMarketIdContains = parsePresetString(preset.negRiskMarketIdContains, "negRiskMarketIdContains");
            const negRiskRequestIdContains = parsePresetString(preset.negRiskRequestIdContains, "negRiskRequestIdContains");
            const questionIdContains = parsePresetString(preset.questionIdContains, "questionIdContains");
            const questionContains = parsePresetString(preset.questionContains, "questionContains");
            const marketSlugContains = parsePresetString(preset.marketSlugContains, "marketSlugContains");
            const iconContains = parsePresetString(preset.iconContains, "iconContains");
            const imageContains = parsePresetString(preset.imageContains, "imageContains");
            const tags = parsePresetTags(preset.tags);
            const activeFilterValue = parsePresetBoolean(preset.active, "active");
            const closedFilterValue = parsePresetBoolean(preset.closed, "closed");
            const archivedFilterValue = parsePresetBoolean(preset.archived, "archived");
            const isFiftyFiftyOutcomeValue = parsePresetBoolean(preset.isFiftyFiftyOutcome, "isFiftyFiftyOutcome");
            const acceptingOrdersValue = parsePresetBoolean(preset.acceptingOrders, "acceptingOrders");
            const enableOrderBookValue = parsePresetBoolean(preset.enableOrderBook, "enableOrderBook");
            const notificationsEnabledValue = parsePresetBoolean(preset.notificationsEnabled, "notificationsEnabled");
            const negRiskValue = parsePresetBoolean(preset.negRisk, "negRisk");
            const rewardsHasRatesValue = parsePresetBoolean(preset.rewardsHasRates, "rewardsHasRates");
            const normalizedPreset = {
                chainId: chainIdValue,
                wsUrl: toOptionalString(wsUrlValue),
                clobApiUrl: toOptionalString(clobApiUrlValue),
                wsConnectTimeoutMs: toOptionalNumber(wsConnectTimeoutMs),
                wsChunkSize: toOptionalNumber(wsChunkSize),
                marketFetchTimeoutMs: toOptionalNumber(marketFetchTimeoutMs),
                maxMarkets: toOptionalNumber(maxMarkets),
                active: activeFilterValue || undefined,
                closed: closedFilterValue || undefined,
                archived: archivedFilterValue || undefined,
                isFiftyFiftyOutcome: isFiftyFiftyOutcomeValue || undefined,
                acceptingOrders: acceptingOrdersValue || undefined,
                enableOrderBook: enableOrderBookValue || undefined,
                notificationsEnabled: notificationsEnabledValue || undefined,
                negRisk: negRiskValue || undefined,
                rewardsHasRates: rewardsHasRatesValue || undefined,
                minimumOrderSizeMin: toOptionalNumber(minimumOrderSizeMin),
                minimumOrderSizeMax: toOptionalNumber(minimumOrderSizeMax),
                minimumTickSizeMin: toOptionalNumber(minimumTickSizeMin),
                minimumTickSizeMax: toOptionalNumber(minimumTickSizeMax),
                makerBaseFeeMin: toOptionalNumber(makerBaseFeeMin),
                makerBaseFeeMax: toOptionalNumber(makerBaseFeeMax),
                takerBaseFeeMin: toOptionalNumber(takerBaseFeeMin),
                takerBaseFeeMax: toOptionalNumber(takerBaseFeeMax),
                secondsDelayMin: toOptionalNumber(secondsDelayMin),
                secondsDelayMax: toOptionalNumber(secondsDelayMax),
                acceptingOrderTimestampMin: toOptionalNumber(acceptingOrderTimestampMin),
                acceptingOrderTimestampMax: toOptionalNumber(acceptingOrderTimestampMax),
                rewardsMinSizeMin: toOptionalNumber(rewardsMinSizeMin),
                rewardsMinSizeMax: toOptionalNumber(rewardsMinSizeMax),
                rewardsMaxSpreadMin: toOptionalNumber(rewardsMaxSpreadMin),
                rewardsMaxSpreadMax: toOptionalNumber(rewardsMaxSpreadMax),
                endDateIsoMin: toOptionalString(endDateIsoMin),
                endDateIsoMax: toOptionalString(endDateIsoMax),
                gameStartTimeMin: toOptionalString(gameStartTimeMin),
                gameStartTimeMax: toOptionalString(gameStartTimeMax),
                descriptionContains: toOptionalString(descriptionContains),
                conditionIdContains: toOptionalString(conditionIdContains),
                fpmm: toOptionalString(fpmmContains),
                negRiskMarketIdContains: toOptionalString(negRiskMarketIdContains),
                negRiskRequestIdContains: toOptionalString(negRiskRequestIdContains),
                questionIdContains: toOptionalString(questionIdContains),
                questionContains: toOptionalString(questionContains),
                marketSlugContains: toOptionalString(marketSlugContains),
                iconContains: toOptionalString(iconContains),
                imageContains: toOptionalString(imageContains),
            };
            const tagsValue = tags
                .split(",")
                .map((item) => item.trim())
                .filter((item) => item.length > 0);
            if (tagsValue.length > 0) {
                normalizedPreset.tags = tagsValue;
            }
            setChainIdInput(String(chainIdValue));
            setWsUrlInput(wsUrlValue);
            setClobApiUrlInput(clobApiUrlValue);
            setWsConnectTimeoutMsInput(wsConnectTimeoutMs);
            setWsChunkSizeInput(wsChunkSize);
            setMarketFetchTimeoutMsInput(marketFetchTimeoutMs);
            setMaxMarketsInput(maxMarkets);
            setActiveFilter(activeFilterValue);
            setClosedFilter(closedFilterValue);
            setArchivedFilter(archivedFilterValue);
            setIsFiftyFiftyOutcomeFilter(isFiftyFiftyOutcomeValue);
            setAcceptingOrdersFilter(acceptingOrdersValue);
            setEnableOrderBookFilter(enableOrderBookValue);
            setNotificationsEnabledFilter(notificationsEnabledValue);
            setNegRiskFilter(negRiskValue);
            setRewardsHasRatesFilter(rewardsHasRatesValue);
            setMinimumOrderSizeMinInput(minimumOrderSizeMin);
            setMinimumOrderSizeMaxInput(minimumOrderSizeMax);
            setMinimumTickSizeMinInput(minimumTickSizeMin);
            setMinimumTickSizeMaxInput(minimumTickSizeMax);
            setMakerBaseFeeMinInput(makerBaseFeeMin);
            setMakerBaseFeeMaxInput(makerBaseFeeMax);
            setTakerBaseFeeMinInput(takerBaseFeeMin);
            setTakerBaseFeeMaxInput(takerBaseFeeMax);
            setSecondsDelayMinInput(secondsDelayMin);
            setSecondsDelayMaxInput(secondsDelayMax);
            setAcceptingOrderTimestampMinInput(acceptingOrderTimestampMin);
            setAcceptingOrderTimestampMaxInput(acceptingOrderTimestampMax);
            setEndDateIsoMinInput(endDateIsoMin);
            setEndDateIsoMaxInput(endDateIsoMax);
            setGameStartTimeMinInput(gameStartTimeMin);
            setGameStartTimeMaxInput(gameStartTimeMax);
            setDescriptionContainsInput(descriptionContains);
            setConditionIdContainsInput(conditionIdContains);
            setFpmmContainsInput(fpmmContains);
            setNegRiskMarketIdContainsInput(negRiskMarketIdContains);
            setNegRiskRequestIdContainsInput(negRiskRequestIdContains);
            setQuestionIdContainsInput(questionIdContains);
            setQuestionContainsInput(questionContains);
            setMarketSlugContainsInput(marketSlugContains);
            setIconContainsInput(iconContains);
            setImageContainsInput(imageContains);
            setTagsInput(tags);
            setRewardsMinSizeMinInput(rewardsMinSizeMin);
            setRewardsMinSizeMaxInput(rewardsMinSizeMax);
            setRewardsMaxSpreadMinInput(rewardsMaxSpreadMin);
            setRewardsMaxSpreadMaxInput(rewardsMaxSpreadMax);
            setPresetInput(JSON.stringify(normalizedPreset, null, 2));
            setFormError(null);
        }
        catch (error) {
            setPresetError(error instanceof Error ? error.message : "Failed to load preset");
        }
    };
    useEffect(() => {
        const controller = new AbortController();
        const refreshActiveRuns = () => {
            void loadActiveRuns(controller.signal);
        };
        refreshActiveRuns();
        const timer = window.setInterval(() => {
            void refreshActiveRuns();
        }, 4000);
        return () => {
            controller.abort();
            clearInterval(timer);
        };
    }, []);
    const validateRange = (min, max, message) => {
        if (min !== undefined && max !== undefined && max < min) {
            setFormError(message);
            return false;
        }
        return true;
    };
    const handleStart = async () => {
        try {
            setFormError(null);
            setPresetError(null);
            setPreviewError(null);
            setPreviewResult(null);
            clearError();
            const request = buildDiscoveryRequest();
            await start(request);
        }
        catch (error) {
            setFormError(error instanceof Error ? error.message : "Invalid filter input");
        }
    };
    const handlePreview = async () => {
        try {
            setFormError(null);
            setPresetError(null);
            setPreviewError(null);
            setPreviewResult(null);
            setPreviewing(true);
            const request = buildDiscoveryRequest();
            const previewRequest = {
                ...request,
                sampleLimit: request.maxMarkets ?? 10,
            };
            const result = await estimateDiscoveryRun(previewRequest);
            setPreviewResult(result);
        }
        catch (error) {
            if (isDiscoveryApiError(error)) {
                setPreviewError(`${error.message} (requestId: ${error.requestId})`);
            }
            else {
                setPreviewError(error instanceof Error ? error.message : "Failed to run preview");
            }
        }
        finally {
            setPreviewing(false);
        }
    };
    return (_jsxs("main", { className: "app", children: [_jsx("h1", { children: "Polymarket discovery" }), _jsxs("section", { className: "card", children: [_jsx(DiscoveryLauncher, { chainIdInput: chainIdInput, clobApiUrlInput: clobApiUrlInput, maxMarketsInput: maxMarketsInput, presetInput: presetInput, presetError: presetError, wsUrlInput: wsUrlInput, wsConnectTimeoutMsInput: wsConnectTimeoutMsInput, wsChunkSizeInput: wsChunkSizeInput, marketFetchTimeoutMsInput: marketFetchTimeoutMsInput, activeFilter: activeFilter, closedFilter: closedFilter, archivedFilter: archivedFilter, isFiftyFiftyOutcomeFilter: isFiftyFiftyOutcomeFilter, acceptingOrdersFilter: acceptingOrdersFilter, enableOrderBookFilter: enableOrderBookFilter, notificationsEnabledFilter: notificationsEnabledFilter, negRiskFilter: negRiskFilter, minimumOrderSizeMinInput: minimumOrderSizeMinInput, minimumOrderSizeMaxInput: minimumOrderSizeMaxInput, minimumTickSizeMinInput: minimumTickSizeMinInput, minimumTickSizeMaxInput: minimumTickSizeMaxInput, makerBaseFeeMinInput: makerBaseFeeMinInput, makerBaseFeeMaxInput: makerBaseFeeMaxInput, takerBaseFeeMinInput: takerBaseFeeMinInput, takerBaseFeeMaxInput: takerBaseFeeMaxInput, secondsDelayMinInput: secondsDelayMinInput, secondsDelayMaxInput: secondsDelayMaxInput, acceptingOrderTimestampMinInput: acceptingOrderTimestampMinInput, acceptingOrderTimestampMaxInput: acceptingOrderTimestampMaxInput, endDateIsoMinInput: endDateIsoMinInput, endDateIsoMaxInput: endDateIsoMaxInput, gameStartTimeMinInput: gameStartTimeMinInput, gameStartTimeMaxInput: gameStartTimeMaxInput, descriptionContainsInput: descriptionContainsInput, conditionIdContainsInput: conditionIdContainsInput, fpmmContainsInput: fpmmContainsInput, negRiskMarketIdContainsInput: negRiskMarketIdContainsInput, negRiskRequestIdContainsInput: negRiskRequestIdContainsInput, questionIdContainsInput: questionIdContainsInput, rewardsHasRatesFilter: rewardsHasRatesFilter, rewardsMinSizeMinInput: rewardsMinSizeMinInput, rewardsMinSizeMaxInput: rewardsMinSizeMaxInput, rewardsMaxSpreadMinInput: rewardsMaxSpreadMinInput, rewardsMaxSpreadMaxInput: rewardsMaxSpreadMaxInput, iconContainsInput: iconContainsInput, imageContainsInput: imageContainsInput, tagsInput: tagsInput, questionContainsInput: questionContainsInput, marketSlugContainsInput: marketSlugContainsInput, onChainIdChange: setChainIdInput, onClobApiUrlChange: setClobApiUrlInput, onWsUrlChange: setWsUrlInput, onWsConnectTimeoutMsChange: setWsConnectTimeoutMsInput, onWsChunkSizeChange: setWsChunkSizeInput, onMarketFetchTimeoutMsChange: setMarketFetchTimeoutMsInput, onMaxMarketsChange: setMaxMarketsInput, onActiveFilterChange: setActiveFilter, onClosedFilterChange: setClosedFilter, onArchivedFilterChange: setArchivedFilter, onIsFiftyFiftyOutcomeFilterChange: setIsFiftyFiftyOutcomeFilter, onAcceptingOrdersFilterChange: setAcceptingOrdersFilter, onEnableOrderBookFilterChange: setEnableOrderBookFilter, onNotificationsEnabledFilterChange: setNotificationsEnabledFilter, onNegRiskFilterChange: setNegRiskFilter, onMinimumOrderSizeMinInputChange: setMinimumOrderSizeMinInput, onMinimumOrderSizeMaxInputChange: setMinimumOrderSizeMaxInput, onMinimumTickSizeMinInputChange: setMinimumTickSizeMinInput, onMinimumTickSizeMaxInputChange: setMinimumTickSizeMaxInput, onMakerBaseFeeMinInputChange: setMakerBaseFeeMinInput, onMakerBaseFeeMaxInputChange: setMakerBaseFeeMaxInput, onTakerBaseFeeMinInputChange: setTakerBaseFeeMinInput, onTakerBaseFeeMaxInputChange: setTakerBaseFeeMaxInput, onSecondsDelayMinInputChange: setSecondsDelayMinInput, onSecondsDelayMaxInputChange: setSecondsDelayMaxInput, onAcceptingOrderTimestampMinInputChange: setAcceptingOrderTimestampMinInput, onAcceptingOrderTimestampMaxInputChange: setAcceptingOrderTimestampMaxInput, onEndDateIsoMinInputChange: setEndDateIsoMinInput, onEndDateIsoMaxInputChange: setEndDateIsoMaxInput, onGameStartTimeMinInputChange: setGameStartTimeMinInput, onGameStartTimeMaxInputChange: setGameStartTimeMaxInput, onDescriptionContainsInputChange: setDescriptionContainsInput, onConditionIdContainsInputChange: setConditionIdContainsInput, onFpmmContainsInputChange: setFpmmContainsInput, onNegRiskMarketIdContainsInputChange: setNegRiskMarketIdContainsInput, onNegRiskRequestIdContainsInputChange: setNegRiskRequestIdContainsInput, onQuestionIdContainsInputChange: setQuestionIdContainsInput, onRewardsHasRatesFilterChange: setRewardsHasRatesFilter, onRewardsMinSizeMinInputChange: setRewardsMinSizeMinInput, onRewardsMinSizeMaxInputChange: setRewardsMinSizeMaxInput, onRewardsMaxSpreadMinInputChange: setRewardsMaxSpreadMinInput, onRewardsMaxSpreadMaxInputChange: setRewardsMaxSpreadMaxInput, onIconContainsInputChange: setIconContainsInput, onImageContainsInputChange: setImageContainsInput, onTagsInputChange: setTagsInput, onQuestionContainsInputChange: setQuestionContainsInput, onMarketSlugContainsInputChange: setMarketSlugContainsInput, onPresetInputChange: (value) => {
                            setPresetInput(value);
                            setPresetError(null);
                        }, onPresetLoad: handlePresetLoad, onPresetCopy: handlePresetCopy, onStart: handleStart, onPreview: handlePreview, onCancel: stop, disabled: false, busy: isBusy, previewing: previewing }), formError ? _jsx("p", { className: "field-error", children: formError }) : null] }), previewError || previewResult ? (_jsxs("section", { className: "card", children: [_jsx("h3", { children: "Discovery preview" }), previewError ? _jsx("p", { className: "field-error", children: previewError }) : null, previewResult ? (_jsxs(_Fragment, { children: [_jsxs("div", { className: "preview-meta", children: [_jsxs("p", { children: [_jsx("strong", { children: "Request ID:" }), " ", previewResult.requestId] }), _jsxs("p", { children: [_jsx("strong", { children: "Sample limit:" }), " ", previewResult.sampleLimit] }), _jsxs("p", { children: [_jsx("strong", { children: "Chain:" }), " ", previewResult.source.chainId] }), _jsxs("p", { children: [_jsx("strong", { children: "Markets scanned:" }), " ", previewResult.source.marketCount] }), _jsxs("p", { children: [_jsx("strong", { children: "Channels in sample:" }), " ", previewResult.source.marketChannelCount] }), _jsxs("p", { children: [_jsx("strong", { children: "Pages scanned:" }), " ", previewResult.source.pagesScanned] }), _jsxs("p", { children: [_jsx("strong", { children: "Likely more matches:" }), " ", previewResult.hasMore ? "Yes" : "No"] }), _jsxs("p", { children: [_jsx("strong", { children: "Stopped by limit:" }), " ", previewResult.stoppedByLimit ? "Yes" : "No"] })] }), _jsx("div", { className: "channels-shell", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Asset ID" }), _jsx("th", { children: "Condition ID" }), _jsx("th", { children: "Question" }), _jsx("th", { children: "Outcome" }), _jsx("th", { children: "Market slug" })] }) }), _jsx("tbody", { children: previewResult.channels.length === 0 ? (_jsx("tr", { children: _jsx("td", { colSpan: 5, children: "No channels matched in sample." }) })) : (previewResult.channels.map((channel) => (_jsxs("tr", { children: [_jsx("td", { children: channel.assetId }), _jsx("td", { children: channel.conditionId || "—" }), _jsx("td", { children: channel.question || "—" }), _jsx("td", { children: channel.outcome || "—" }), _jsx("td", { children: channel.marketSlug || "—" })] }, channel.assetId)))) })] }) })] })) : null] })) : null, _jsxs("section", { className: "card", children: [_jsx("h3", { children: "Active discovery jobs" }), activeRunsError ? (_jsxs("p", { className: "field-error", children: [_jsx("strong", { children: activeRunsError.error }), ": ", activeRunsError.message] })) : null, activeRuns.length === 0 ? (_jsx("p", { children: "No active discovery jobs." })) : (_jsx("div", { className: "channels-shell", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Run ID" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Chain" }), _jsx("th", { children: "Requested" }), _jsx("th", { children: "Started" }), _jsx("th", { children: "Markets" }), _jsx("th", { children: "Channels" }), _jsx("th", { children: "Open" }), _jsx("th", { children: "Actions" })] }) }), _jsx("tbody", { children: activeRuns.map((activeRun) => (_jsxs("tr", { children: [_jsx("td", { children: activeRun.run.id }), _jsx("td", { children: activeRun.run.status }), _jsx("td", { children: activeRun.run.source.chainId }), _jsx("td", { children: formatDate(activeRun.run.requestedAt) }), _jsx("td", { children: formatDate(activeRun.run.startedAt) }), _jsx("td", { children: activeRun.run.marketCount }), _jsx("td", { children: activeRun.run.marketChannelCount }), _jsx("td", { children: _jsx("a", { href: activeRun.pollUrl, children: "Open" }) }), _jsx("td", { children: _jsx("button", { type: "button", className: "danger", onClick: () => void handleCancelRun(activeRun.run.id), disabled: cancelingRunIds.has(activeRun.run.id), children: cancelingRunIds.has(activeRun.run.id) ? "Canceling…" : "Cancel" }) })] }, activeRun.run.id))) })] }) }))] }), state.phase === "error" && state.error ? _jsx(DiscoveryErrorBanner, { error: state.error }) : null, _jsx(RunStatusPanel, { phase: state.phase, shell: state.shell, run: state.run }), _jsxs("div", { className: "card row actions-card", children: [_jsx("button", { type: "button", onClick: refreshCurrentPage, disabled: !state.shell, children: "Refresh current page" }), _jsx("button", { type: "button", onClick: () => goToPage(prevOffset), disabled: !canPrevPage, children: "Previous page" }), _jsx("button", { type: "button", onClick: () => goToPage(nextOffset), disabled: !canNextPage, children: "Next page" })] }), _jsx(ChannelsTable, { model: state.run, phase: state.phase, onPrevious: canPrevPage ? () => goToPage(prevOffset) : undefined, onNext: canNextPage ? () => goToPage(nextOffset) : undefined }), _jsxs("section", { className: "card small-note", children: [_jsx("h3", { children: "Run lifecycle" }), _jsxs("ul", { children: [_jsxs("li", { children: [_jsx("strong", { children: "submitting" }), ": create/attach run on server"] }), _jsxs("li", { children: [_jsx("strong", { children: "polling" }), ": GET run endpoint with pagination until terminal"] }), _jsxs("li", { children: [_jsx("strong", { children: "completed" }), ": run finished successfully or partially"] }), _jsxs("li", { children: [_jsx("strong", { children: "failed" }), ": run completed with terminal failure"] }), _jsxs("li", { children: [_jsx("strong", { children: "error" }), ": transport / validation contract error"] })] }), state.run ? _jsxs("p", { children: ["Last known requestId: ", state.run.run.requestId] }) : null, (state.phase === "completed" || state.phase === "failed") && state.run ? (_jsxs("p", { children: ["Terminal status: ", state.run.run.status] })) : null] })] }));
}
