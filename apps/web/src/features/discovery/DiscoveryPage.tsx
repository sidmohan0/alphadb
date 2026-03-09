import { useEffect, useMemo, useState } from "react";

import { cancelDiscoveryRun, estimateDiscoveryRun, listActiveDiscoveryRuns } from "./api/discoveryApi";
import { useDiscoveryPoller } from "./hooks/useDiscoveryPoller";
import type {
  DiscoveryActiveRun,
  DiscoveryApiError,
  DiscoveryEstimateResult,
  StartDiscoveryEstimateRequest,
  StartDiscoveryRequest,
} from "./types";
import { DiscoveryErrorBanner } from "./components/DiscoveryErrorBanner";
import { DiscoveryLauncher } from "./components/DiscoveryLauncher";
import { ChannelsTable } from "./components/ChannelsTable";
import { RunStatusPanel } from "./components/RunStatusPanel";

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

function formatDate(value?: string): string {
  if (!value) {
    return "—";
  }

  return new Date(value).toLocaleString();
}

function parseNonNegativeInput(value: string, fieldLabel: string): number | undefined {
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

function parsePositiveIntInput(value: string, fieldLabel: string): number | undefined {
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

function parseDateTimeInput(value: string, fieldLabel: string): string | undefined {
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

function toLocalDateTimeInput(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    return "";
  }

  const date = new Date(parsed);
  const pad = (number: number): string => number.toString().padStart(2, "0");

  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function DiscoveryPage(): JSX.Element {
  const {
    state,
    start,
    stop,
    refreshCurrentPage,
    goToPage,
    clearError,
  } = useDiscoveryPoller({
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
  const [presetError, setPresetError] = useState<string | null>(null);

  const [formError, setFormError] = useState<string | null>(null);
  const [activeRuns, setActiveRuns] = useState<DiscoveryActiveRun[]>([]);
  const [activeRunsError, setActiveRunsError] = useState<DiscoveryApiError | null>(null);
  const [cancelingRunIds, setCancelingRunIds] = useState<Set<string>>(new Set());
  const [previewResult, setPreviewResult] = useState<DiscoveryEstimateResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
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

  const loadActiveRuns = async (signal?: AbortSignal): Promise<void> => {
    try {
      const payload = await listActiveDiscoveryRuns(signal);
      setActiveRuns(payload.runs);
      setActiveRunsError(null);
    } catch (error) {
      if ((error as { name?: string }).name === "AbortError") {
        return;
      }

      setActiveRunsError(
        isDiscoveryApiError(error)
          ? error
          : {
              error: "Discovery request failed",
              code: "unexpected_error",
              message: "Failed to fetch active discovery jobs",
              retryable: false,
              requestId: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
            }
      );
    }
  };

  const handleCancelRun = async (runId: string): Promise<void> => {
    setCancelingRunIds((current) => {
      const next = new Set(current);
      next.add(runId);
      return next;
    });

    try {
      await cancelDiscoveryRun(runId);
      setActiveRunsError(null);
      await loadActiveRuns();
    } catch (error) {
      setActiveRunsError(
        isDiscoveryApiError(error)
          ? error
          : {
              error: "Discovery request failed",
              code: "unexpected_error",
              message: "Failed to cancel discovery run",
              retryable: false,
              requestId: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
            }
      );
    } finally {
      setCancelingRunIds((current) => {
        const next = new Set(current);
        next.delete(runId);
        return next;
      });
    }
  };

  const parsePresetBoolean = (value: unknown, fieldLabel: string): boolean => {
    if (value === undefined || value === null) {
      return false;
    }

    if (typeof value !== "boolean") {
      throw new Error(`${fieldLabel} must be a boolean`);
    }

    return value;
  };

  const parsePresetString = (value: unknown, fieldLabel: string): string => {
    if (value === undefined || value === null) {
      return "";
    }

    if (typeof value !== "string") {
      throw new Error(`${fieldLabel} must be a string`);
    }

    return value.trim();
  };

  const parsePresetNumber = (value: unknown, fieldLabel: string): string => {
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

  const parsePresetPositiveInt = (value: unknown, fieldLabel: string): string => {
    if (value === undefined || value === null) {
      return "";
    }

    const parsed = typeof value === "number" ? value : Number(String(value).trim());
    if (!Number.isInteger(parsed) || parsed <= 0) {
      throw new Error(`${fieldLabel} must be a positive integer`);
    }

    return parsed.toString();
  };

  const parsePresetDateTime = (value: unknown, fieldLabel: string): string => {
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

  const parsePresetTags = (value: unknown): string => {
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

  const buildDiscoveryRequest = (): StartDiscoveryRequest => {
    const parsedChainId = Number(chainIdInput);
    if (!Number.isInteger(parsedChainId) || parsedChainId <= 0) {
      throw new Error("chainId must be a positive integer");
    }

    const request: StartDiscoveryRequest = {
      chainId: parsedChainId,
      wsUrl: wsUrlInput.trim() || undefined,
    };

    const clobApiUrlValue = clobApiUrlInput.trim();
    if (clobApiUrlValue) {
      request.clobApiUrl = clobApiUrlValue;
    }

    request.wsConnectTimeoutMs = parsePositiveIntInput(
      wsConnectTimeoutMsInput,
      "wsConnectTimeoutMs"
    );
    request.wsChunkSize = parsePositiveIntInput(wsChunkSizeInput, "wsChunkSize");
    request.marketFetchTimeoutMs = parsePositiveIntInput(
      marketFetchTimeoutMsInput,
      "marketFetchTimeoutMs"
    );
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
    if (
      !validateRange(
        request.rewardsMinSizeMin,
        request.rewardsMinSizeMax,
        "rewardsMinSizeMax must be >= rewardsMinSizeMin"
      )
    ) {
      throw new Error("rewardsMinSizeMax must be >= rewardsMinSizeMin");
    }

    request.rewardsMaxSpreadMin = parseNonNegativeInput(rewardsMaxSpreadMinInput, "rewardsMaxSpreadMin");
    request.rewardsMaxSpreadMax = parseNonNegativeInput(rewardsMaxSpreadMaxInput, "rewardsMaxSpreadMax");
    if (
      !validateRange(
        request.rewardsMaxSpreadMin,
        request.rewardsMaxSpreadMax,
        "rewardsMaxSpreadMax must be >= rewardsMaxSpreadMin"
      )
    ) {
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

    request.acceptingOrderTimestampMin = parseNonNegativeInput(
      acceptingOrderTimestampMinInput,
      "acceptingOrderTimestampMin"
    );
    request.acceptingOrderTimestampMax = parseNonNegativeInput(
      acceptingOrderTimestampMaxInput,
      "acceptingOrderTimestampMax"
    );
    if (
      !validateRange(
        request.acceptingOrderTimestampMin,
        request.acceptingOrderTimestampMax,
        "acceptingOrderTimestampMax must be >= acceptingOrderTimestampMin"
      )
    ) {
      throw new Error("acceptingOrderTimestampMax must be >= acceptingOrderTimestampMin");
    }

    request.endDateIsoMin = parseDateTimeInput(endDateIsoMinInput, "endDateIsoMin");
    request.endDateIsoMax = parseDateTimeInput(endDateIsoMaxInput, "endDateIsoMax");
    if (
      request.endDateIsoMin !== undefined &&
      request.endDateIsoMax !== undefined &&
      Date.parse(request.endDateIsoMax) < Date.parse(request.endDateIsoMin)
    ) {
      throw new Error("endDateIsoMax must be >= endDateIsoMin");
    }

    request.gameStartTimeMin = parseDateTimeInput(gameStartTimeMinInput, "gameStartTimeMin");
    request.gameStartTimeMax = parseDateTimeInput(gameStartTimeMaxInput, "gameStartTimeMax");
    if (
      request.gameStartTimeMin !== undefined &&
      request.gameStartTimeMax !== undefined &&
      Date.parse(request.gameStartTimeMax) < Date.parse(request.gameStartTimeMin)
    ) {
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

  const handlePresetCopy = async (): Promise<void> => {
    try {
      const request = buildDiscoveryRequest();
      const nextPreset = JSON.stringify(request, null, 2);
      setPresetInput(nextPreset);
      setPresetError(null);

      if (typeof navigator === "undefined" || typeof navigator.clipboard?.writeText !== "function") {
        throw new Error("Clipboard API is unavailable in this browser context");
      }

      await navigator.clipboard.writeText(nextPreset);
    } catch (error) {
      setPresetError(error instanceof Error ? error.message : "Failed to copy preset");
    }
  };

  const handlePresetLoad = (): void => {
    try {
      setPresetError(null);
      const parsed = JSON.parse(presetInput);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Preset must be a JSON object");
      }

      const preset = parsed as Record<string, unknown>;
      const toOptionalNumber = (value: string): number | undefined => (value ? Number(value) : undefined);
      const toOptionalString = (value: string): string | undefined => (value ? value : undefined);

      const chainIdValue =
        preset.chainId !== undefined
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
      const marketFetchTimeoutMs = parsePresetPositiveInt(
        preset.marketFetchTimeoutMs,
        "marketFetchTimeoutMs"
      );
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

      const normalizedPreset: StartDiscoveryRequest = {
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
    } catch (error) {
      setPresetError(error instanceof Error ? error.message : "Failed to load preset");
    }
  };

  useEffect(() => {
    const controller = new AbortController();

    const refreshActiveRuns = (): void => {
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

  const validateRange = (min: number | undefined, max: number | undefined, message: string): boolean => {
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
    } catch (error) {
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
      const previewRequest: StartDiscoveryEstimateRequest = {
        ...request,
        sampleLimit: request.maxMarkets ?? 10,
      };

      const result = await estimateDiscoveryRun(previewRequest);
      setPreviewResult(result);
    } catch (error) {
      if (isDiscoveryApiError(error)) {
        setPreviewError(`${error.message} (requestId: ${error.requestId})`);
      } else {
        setPreviewError(error instanceof Error ? error.message : "Failed to run preview");
      }
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <main className="app">
      <h1>Polymarket discovery</h1>

      <section className="card">
        <DiscoveryLauncher
          chainIdInput={chainIdInput}
          clobApiUrlInput={clobApiUrlInput}
          maxMarketsInput={maxMarketsInput}
          presetInput={presetInput}
          presetError={presetError}
          wsUrlInput={wsUrlInput}
          wsConnectTimeoutMsInput={wsConnectTimeoutMsInput}
          wsChunkSizeInput={wsChunkSizeInput}
          marketFetchTimeoutMsInput={marketFetchTimeoutMsInput}
          activeFilter={activeFilter}
          closedFilter={closedFilter}
          archivedFilter={archivedFilter}
          isFiftyFiftyOutcomeFilter={isFiftyFiftyOutcomeFilter}
          acceptingOrdersFilter={acceptingOrdersFilter}
          enableOrderBookFilter={enableOrderBookFilter}
          notificationsEnabledFilter={notificationsEnabledFilter}
          negRiskFilter={negRiskFilter}
          minimumOrderSizeMinInput={minimumOrderSizeMinInput}
          minimumOrderSizeMaxInput={minimumOrderSizeMaxInput}
          minimumTickSizeMinInput={minimumTickSizeMinInput}
          minimumTickSizeMaxInput={minimumTickSizeMaxInput}
          makerBaseFeeMinInput={makerBaseFeeMinInput}
          makerBaseFeeMaxInput={makerBaseFeeMaxInput}
          takerBaseFeeMinInput={takerBaseFeeMinInput}
          takerBaseFeeMaxInput={takerBaseFeeMaxInput}
          secondsDelayMinInput={secondsDelayMinInput}
          secondsDelayMaxInput={secondsDelayMaxInput}
          acceptingOrderTimestampMinInput={acceptingOrderTimestampMinInput}
          acceptingOrderTimestampMaxInput={acceptingOrderTimestampMaxInput}
          endDateIsoMinInput={endDateIsoMinInput}
          endDateIsoMaxInput={endDateIsoMaxInput}
          gameStartTimeMinInput={gameStartTimeMinInput}
          gameStartTimeMaxInput={gameStartTimeMaxInput}
          descriptionContainsInput={descriptionContainsInput}
          conditionIdContainsInput={conditionIdContainsInput}
          fpmmContainsInput={fpmmContainsInput}
          negRiskMarketIdContainsInput={negRiskMarketIdContainsInput}
          negRiskRequestIdContainsInput={negRiskRequestIdContainsInput}
          questionIdContainsInput={questionIdContainsInput}
          rewardsHasRatesFilter={rewardsHasRatesFilter}
          rewardsMinSizeMinInput={rewardsMinSizeMinInput}
          rewardsMinSizeMaxInput={rewardsMinSizeMaxInput}
          rewardsMaxSpreadMinInput={rewardsMaxSpreadMinInput}
          rewardsMaxSpreadMaxInput={rewardsMaxSpreadMaxInput}
          iconContainsInput={iconContainsInput}
          imageContainsInput={imageContainsInput}
          tagsInput={tagsInput}
          questionContainsInput={questionContainsInput}
          marketSlugContainsInput={marketSlugContainsInput}
          onChainIdChange={setChainIdInput}
          onClobApiUrlChange={setClobApiUrlInput}
          onWsUrlChange={setWsUrlInput}
          onWsConnectTimeoutMsChange={setWsConnectTimeoutMsInput}
          onWsChunkSizeChange={setWsChunkSizeInput}
          onMarketFetchTimeoutMsChange={setMarketFetchTimeoutMsInput}
          onMaxMarketsChange={setMaxMarketsInput}
          onActiveFilterChange={setActiveFilter}
          onClosedFilterChange={setClosedFilter}
          onArchivedFilterChange={setArchivedFilter}
          onIsFiftyFiftyOutcomeFilterChange={setIsFiftyFiftyOutcomeFilter}
          onAcceptingOrdersFilterChange={setAcceptingOrdersFilter}
          onEnableOrderBookFilterChange={setEnableOrderBookFilter}
          onNotificationsEnabledFilterChange={setNotificationsEnabledFilter}
          onNegRiskFilterChange={setNegRiskFilter}
          onMinimumOrderSizeMinInputChange={setMinimumOrderSizeMinInput}
          onMinimumOrderSizeMaxInputChange={setMinimumOrderSizeMaxInput}
          onMinimumTickSizeMinInputChange={setMinimumTickSizeMinInput}
          onMinimumTickSizeMaxInputChange={setMinimumTickSizeMaxInput}
          onMakerBaseFeeMinInputChange={setMakerBaseFeeMinInput}
          onMakerBaseFeeMaxInputChange={setMakerBaseFeeMaxInput}
          onTakerBaseFeeMinInputChange={setTakerBaseFeeMinInput}
          onTakerBaseFeeMaxInputChange={setTakerBaseFeeMaxInput}
          onSecondsDelayMinInputChange={setSecondsDelayMinInput}
          onSecondsDelayMaxInputChange={setSecondsDelayMaxInput}
          onAcceptingOrderTimestampMinInputChange={setAcceptingOrderTimestampMinInput}
          onAcceptingOrderTimestampMaxInputChange={setAcceptingOrderTimestampMaxInput}
          onEndDateIsoMinInputChange={setEndDateIsoMinInput}
          onEndDateIsoMaxInputChange={setEndDateIsoMaxInput}
          onGameStartTimeMinInputChange={setGameStartTimeMinInput}
          onGameStartTimeMaxInputChange={setGameStartTimeMaxInput}
          onDescriptionContainsInputChange={setDescriptionContainsInput}
          onConditionIdContainsInputChange={setConditionIdContainsInput}
          onFpmmContainsInputChange={setFpmmContainsInput}
          onNegRiskMarketIdContainsInputChange={setNegRiskMarketIdContainsInput}
          onNegRiskRequestIdContainsInputChange={setNegRiskRequestIdContainsInput}
          onQuestionIdContainsInputChange={setQuestionIdContainsInput}
          onRewardsHasRatesFilterChange={setRewardsHasRatesFilter}
          onRewardsMinSizeMinInputChange={setRewardsMinSizeMinInput}
          onRewardsMinSizeMaxInputChange={setRewardsMinSizeMaxInput}
          onRewardsMaxSpreadMinInputChange={setRewardsMaxSpreadMinInput}
          onRewardsMaxSpreadMaxInputChange={setRewardsMaxSpreadMaxInput}
          onIconContainsInputChange={setIconContainsInput}
          onImageContainsInputChange={setImageContainsInput}
          onTagsInputChange={setTagsInput}
          onQuestionContainsInputChange={setQuestionContainsInput}
          onMarketSlugContainsInputChange={setMarketSlugContainsInput}
          onPresetInputChange={(value: string) => {
            setPresetInput(value);
            setPresetError(null);
          }}
          onPresetLoad={handlePresetLoad}
          onPresetCopy={handlePresetCopy}
          onStart={handleStart}
          onPreview={handlePreview}
          onCancel={stop}
          disabled={false}
          busy={isBusy}
          previewing={previewing}
        />

        {formError ? <p className="field-error">{formError}</p> : null}
      </section>

      {previewError || previewResult ? (
        <section className="card">
          <h3>Discovery preview</h3>
          {previewError ? <p className="field-error">{previewError}</p> : null}
          {previewResult ? (
            <>
              <div className="preview-meta">
                <p>
                  <strong>Request ID:</strong> {previewResult.requestId}
                </p>
                <p>
                  <strong>Sample limit:</strong> {previewResult.sampleLimit}
                </p>
                <p>
                  <strong>Chain:</strong> {previewResult.source.chainId}
                </p>
                <p>
                  <strong>Markets scanned:</strong> {previewResult.source.marketCount}
                </p>
                <p>
                  <strong>Channels in sample:</strong> {previewResult.source.marketChannelCount}
                </p>
                <p>
                  <strong>Pages scanned:</strong> {previewResult.source.pagesScanned}
                </p>
                <p>
                  <strong>Likely more matches:</strong>{" "}
                  {previewResult.hasMore ? "Yes" : "No"}
                </p>
                <p>
                  <strong>Stopped by limit:</strong> {previewResult.stoppedByLimit ? "Yes" : "No"}
                </p>
              </div>

              <div className="channels-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Asset ID</th>
                      <th>Condition ID</th>
                      <th>Question</th>
                      <th>Outcome</th>
                      <th>Market slug</th>
                    </tr>
                  </thead>
                  <tbody>
                    {previewResult.channels.length === 0 ? (
                      <tr>
                        <td colSpan={5}>No channels matched in sample.</td>
                      </tr>
                    ) : (
                      previewResult.channels.map((channel) => (
                        <tr key={channel.assetId}>
                          <td>{channel.assetId}</td>
                          <td>{channel.conditionId || "—"}</td>
                          <td>{channel.question || "—"}</td>
                          <td>{channel.outcome || "—"}</td>
                          <td>{channel.marketSlug || "—"}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      <section className="card">
        <h3>Active discovery jobs</h3>

        {activeRunsError ? (
          <p className="field-error">
            <strong>{activeRunsError.error}</strong>: {activeRunsError.message}
          </p>
        ) : null}

        {activeRuns.length === 0 ? (
          <p>No active discovery jobs.</p>
        ) : (
          <div className="channels-shell">
            <table>
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Chain</th>
                  <th>Requested</th>
                  <th>Started</th>
                  <th>Markets</th>
                  <th>Channels</th>
                  <th>Open</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {activeRuns.map((activeRun) => (
                  <tr key={activeRun.run.id}>
                    <td>{activeRun.run.id}</td>
                    <td>{activeRun.run.status}</td>
                    <td>{activeRun.run.source.chainId}</td>
                    <td>{formatDate(activeRun.run.requestedAt)}</td>
                    <td>{formatDate(activeRun.run.startedAt)}</td>
                    <td>{activeRun.run.marketCount}</td>
                    <td>{activeRun.run.marketChannelCount}</td>
                    <td>
                      <a href={activeRun.pollUrl}>Open</a>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="danger"
                        onClick={() => void handleCancelRun(activeRun.run.id)}
                        disabled={cancelingRunIds.has(activeRun.run.id)}
                      >
                        {cancelingRunIds.has(activeRun.run.id) ? "Canceling…" : "Cancel"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {state.phase === "error" && state.error ? <DiscoveryErrorBanner error={state.error} /> : null}

      <RunStatusPanel phase={state.phase} shell={state.shell} run={state.run} />

      <div className="card row actions-card">
        <button type="button" onClick={refreshCurrentPage} disabled={!state.shell}>
          Refresh current page
        </button>

        <button
          type="button"
          onClick={() => goToPage(prevOffset)}
          disabled={!canPrevPage}
        >
          Previous page
        </button>
        <button
          type="button"
          onClick={() => goToPage(nextOffset)}
          disabled={!canNextPage}
        >
          Next page
        </button>
      </div>

      <ChannelsTable
        model={state.run}
        phase={state.phase}
        onPrevious={canPrevPage ? () => goToPage(prevOffset) : undefined}
        onNext={canNextPage ? () => goToPage(nextOffset) : undefined}
      />

      <section className="card small-note">
        <h3>Run lifecycle</h3>
        <ul>
          <li>
            <strong>submitting</strong>: create/attach run on server
          </li>
          <li>
            <strong>polling</strong>: GET run endpoint with pagination until terminal
          </li>
          <li>
            <strong>completed</strong>: run finished successfully or partially
          </li>
          <li>
            <strong>failed</strong>: run completed with terminal failure
          </li>
          <li>
            <strong>error</strong>: transport / validation contract error
          </li>
        </ul>
        {state.run ? <p>Last known requestId: {state.run.run.requestId}</p> : null}
        {(state.phase === "completed" || state.phase === "failed") && state.run ? (
          <p>Terminal status: {state.run.run.status}</p>
        ) : null}
      </section>
    </main>
  );
}
