import { type FormEvent } from "react";

interface DiscoveryLauncherProps {
  chainIdInput: string;
  clobApiUrlInput: string;
  maxMarketsInput: string;
  wsUrlInput: string;
  wsConnectTimeoutMsInput: string;
  wsChunkSizeInput: string;
  marketFetchTimeoutMsInput: string;
  presetInput: string;
  presetError: string | null;
  activeFilter: boolean;
  closedFilter: boolean;
  archivedFilter: boolean;
  isFiftyFiftyOutcomeFilter: boolean;
  acceptingOrdersFilter: boolean;
  enableOrderBookFilter: boolean;
  notificationsEnabledFilter: boolean;
  negRiskFilter: boolean;
  minimumOrderSizeMinInput: string;
  minimumOrderSizeMaxInput: string;
  minimumTickSizeMinInput: string;
  minimumTickSizeMaxInput: string;
  makerBaseFeeMinInput: string;
  makerBaseFeeMaxInput: string;
  takerBaseFeeMinInput: string;
  takerBaseFeeMaxInput: string;
  secondsDelayMinInput: string;
  secondsDelayMaxInput: string;
  acceptingOrderTimestampMinInput: string;
  acceptingOrderTimestampMaxInput: string;
  endDateIsoMinInput: string;
  endDateIsoMaxInput: string;
  gameStartTimeMinInput: string;
  gameStartTimeMaxInput: string;
  descriptionContainsInput: string;
  conditionIdContainsInput: string;
  fpmmContainsInput: string;
  negRiskMarketIdContainsInput: string;
  negRiskRequestIdContainsInput: string;
  questionIdContainsInput: string;
  rewardsHasRatesFilter: boolean;
  rewardsMinSizeMinInput: string;
  rewardsMinSizeMaxInput: string;
  rewardsMaxSpreadMinInput: string;
  rewardsMaxSpreadMaxInput: string;
  iconContainsInput: string;
  imageContainsInput: string;
  tagsInput: string;
  questionContainsInput: string;
  marketSlugContainsInput: string;
  onChainIdChange: (value: string) => void;
  onClobApiUrlChange: (value: string) => void;
  onMaxMarketsChange: (value: string) => void;
  onWsUrlChange: (value: string) => void;
  onWsConnectTimeoutMsChange: (value: string) => void;
  onWsChunkSizeChange: (value: string) => void;
  onMarketFetchTimeoutMsChange: (value: string) => void;
  onActiveFilterChange: (value: boolean) => void;
  onClosedFilterChange: (value: boolean) => void;
  onArchivedFilterChange: (value: boolean) => void;
  onIsFiftyFiftyOutcomeFilterChange: (value: boolean) => void;
  onAcceptingOrdersFilterChange: (value: boolean) => void;
  onEnableOrderBookFilterChange: (value: boolean) => void;
  onNotificationsEnabledFilterChange: (value: boolean) => void;
  onNegRiskFilterChange: (value: boolean) => void;
  onMinimumOrderSizeMinInputChange: (value: string) => void;
  onMinimumOrderSizeMaxInputChange: (value: string) => void;
  onMinimumTickSizeMinInputChange: (value: string) => void;
  onMinimumTickSizeMaxInputChange: (value: string) => void;
  onMakerBaseFeeMinInputChange: (value: string) => void;
  onMakerBaseFeeMaxInputChange: (value: string) => void;
  onTakerBaseFeeMinInputChange: (value: string) => void;
  onTakerBaseFeeMaxInputChange: (value: string) => void;
  onSecondsDelayMinInputChange: (value: string) => void;
  onSecondsDelayMaxInputChange: (value: string) => void;
  onAcceptingOrderTimestampMinInputChange: (value: string) => void;
  onAcceptingOrderTimestampMaxInputChange: (value: string) => void;
  onEndDateIsoMinInputChange: (value: string) => void;
  onEndDateIsoMaxInputChange: (value: string) => void;
  onGameStartTimeMinInputChange: (value: string) => void;
  onGameStartTimeMaxInputChange: (value: string) => void;
  onDescriptionContainsInputChange: (value: string) => void;
  onConditionIdContainsInputChange: (value: string) => void;
  onFpmmContainsInputChange: (value: string) => void;
  onNegRiskMarketIdContainsInputChange: (value: string) => void;
  onNegRiskRequestIdContainsInputChange: (value: string) => void;
  onQuestionIdContainsInputChange: (value: string) => void;
  onRewardsHasRatesFilterChange: (value: boolean) => void;
  onRewardsMinSizeMinInputChange: (value: string) => void;
  onRewardsMinSizeMaxInputChange: (value: string) => void;
  onRewardsMaxSpreadMinInputChange: (value: string) => void;
  onRewardsMaxSpreadMaxInputChange: (value: string) => void;
  onIconContainsInputChange: (value: string) => void;
  onImageContainsInputChange: (value: string) => void;
  onTagsInputChange: (value: string) => void;
  onQuestionContainsInputChange: (value: string) => void;
  onMarketSlugContainsInputChange: (value: string) => void;
  onPresetInputChange: (value: string) => void;
  onPresetLoad: () => void;
  onPresetCopy: () => void;
  onPreview: () => void;
  onStart: () => void;
  onCancel: () => void;
  disabled: boolean;
  busy: boolean;
  previewing: boolean;
}

export function DiscoveryLauncher({
  chainIdInput,
  clobApiUrlInput,
  maxMarketsInput,
  wsUrlInput,
  wsConnectTimeoutMsInput,
  wsChunkSizeInput,
  marketFetchTimeoutMsInput,
  presetInput,
  presetError,
  activeFilter,
  closedFilter,
  archivedFilter,
  isFiftyFiftyOutcomeFilter,
  acceptingOrdersFilter,
  enableOrderBookFilter,
  notificationsEnabledFilter,
  negRiskFilter,
  minimumOrderSizeMinInput,
  minimumOrderSizeMaxInput,
  minimumTickSizeMinInput,
  minimumTickSizeMaxInput,
  makerBaseFeeMinInput,
  makerBaseFeeMaxInput,
  takerBaseFeeMinInput,
  takerBaseFeeMaxInput,
  secondsDelayMinInput,
  secondsDelayMaxInput,
  acceptingOrderTimestampMinInput,
  acceptingOrderTimestampMaxInput,
  endDateIsoMinInput,
  endDateIsoMaxInput,
  gameStartTimeMinInput,
  gameStartTimeMaxInput,
  descriptionContainsInput,
  conditionIdContainsInput,
  fpmmContainsInput,
  negRiskMarketIdContainsInput,
  negRiskRequestIdContainsInput,
  questionIdContainsInput,
  rewardsHasRatesFilter,
  rewardsMinSizeMinInput,
  rewardsMinSizeMaxInput,
  rewardsMaxSpreadMinInput,
  rewardsMaxSpreadMaxInput,
  iconContainsInput,
  imageContainsInput,
  tagsInput,
  questionContainsInput,
  marketSlugContainsInput,
  onChainIdChange,
  onClobApiUrlChange,
  onMaxMarketsChange,
  onWsUrlChange,
  onWsConnectTimeoutMsChange,
  onWsChunkSizeChange,
  onMarketFetchTimeoutMsChange,
  onActiveFilterChange,
  onClosedFilterChange,
  onArchivedFilterChange,
  onIsFiftyFiftyOutcomeFilterChange,
  onAcceptingOrdersFilterChange,
  onEnableOrderBookFilterChange,
  onNotificationsEnabledFilterChange,
  onNegRiskFilterChange,
  onMinimumOrderSizeMinInputChange,
  onMinimumOrderSizeMaxInputChange,
  onMinimumTickSizeMinInputChange,
  onMinimumTickSizeMaxInputChange,
  onMakerBaseFeeMinInputChange,
  onMakerBaseFeeMaxInputChange,
  onTakerBaseFeeMinInputChange,
  onTakerBaseFeeMaxInputChange,
  onSecondsDelayMinInputChange,
  onSecondsDelayMaxInputChange,
  onAcceptingOrderTimestampMinInputChange,
  onAcceptingOrderTimestampMaxInputChange,
  onEndDateIsoMinInputChange,
  onEndDateIsoMaxInputChange,
  onGameStartTimeMinInputChange,
  onGameStartTimeMaxInputChange,
  onDescriptionContainsInputChange,
  onConditionIdContainsInputChange,
  onFpmmContainsInputChange,
  onNegRiskMarketIdContainsInputChange,
  onNegRiskRequestIdContainsInputChange,
  onQuestionIdContainsInputChange,
  onRewardsHasRatesFilterChange,
  onRewardsMinSizeMinInputChange,
  onRewardsMinSizeMaxInputChange,
  onRewardsMaxSpreadMinInputChange,
  onRewardsMaxSpreadMaxInputChange,
  onIconContainsInputChange,
  onImageContainsInputChange,
  onTagsInputChange,
  onQuestionContainsInputChange,
  onMarketSlugContainsInputChange,
  onPresetInputChange,
  onPresetLoad,
  onPresetCopy,
  onPreview,
  onStart,
  onCancel,
  disabled,
  busy,
  previewing,
}: DiscoveryLauncherProps): JSX.Element {
  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();

    if (!disabled) {
      onStart();
    }
  };

  return (
    <form className="discovery-launcher" onSubmit={handleSubmit}>
      <label>
        Chain ID
        <input
          type="number"
          value={chainIdInput}
          onChange={(event) => onChainIdChange(event.target.value)}
          disabled={busy}
          min={1}
          placeholder="137"
        />
      </label>
      <label>
        Clob API URL (optional)
        <input
          type="text"
          value={clobApiUrlInput}
          onChange={(event) => onClobApiUrlChange(event.target.value)}
          disabled={busy}
          placeholder="https://clob.polymarket.com"
        />
      </label>
      <label>
        Max markets to sample (optional)
        <input
          type="number"
          min={1}
          step={1}
          value={maxMarketsInput}
          onChange={(event) => onMaxMarketsChange(event.target.value)}
          disabled={busy}
          placeholder="e.g. 10"
        />
      </label>

      <label className="preset-block">
        Preset (JSON)
        <textarea
          className="preset-textarea"
          value={presetInput}
          onChange={(event) => onPresetInputChange(event.target.value)}
          disabled={busy}
          rows={8}
          placeholder='{"chainId":137,"active":true,"questionContains":"president"}'
        />
        <div className="button-row">
          <button type="button" className="secondary" onClick={onPresetLoad} disabled={busy || !presetInput.trim()}>
            Load preset
          </button>
          <button type="button" className="secondary" onClick={onPresetCopy} disabled={busy}>
            Copy current preset
          </button>
        </div>
        {presetError ? <p className="field-error">{presetError}</p> : null}
      </label>

      <fieldset className="discovery-filters">
        <legend>Discovery filters</legend>
        <div className="filter-grid">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={activeFilter}
              onChange={(event) => onActiveFilterChange(event.target.checked)}
              disabled={busy}
            />
            Active markets only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={closedFilter}
              onChange={(event) => onClosedFilterChange(event.target.checked)}
              disabled={busy}
            />
            Closed markets only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={archivedFilter}
              onChange={(event) => onArchivedFilterChange(event.target.checked)}
              disabled={busy}
            />
            Archived markets only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={isFiftyFiftyOutcomeFilter}
              onChange={(event) => onIsFiftyFiftyOutcomeFilterChange(event.target.checked)}
              disabled={busy}
            />
            50/50 markets only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={acceptingOrdersFilter}
              onChange={(event) => onAcceptingOrdersFilterChange(event.target.checked)}
              disabled={busy}
            />
            Accepting orders only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={enableOrderBookFilter}
              onChange={(event) => onEnableOrderBookFilterChange(event.target.checked)}
              disabled={busy}
            />
            Enable order book only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={notificationsEnabledFilter}
              onChange={(event) => onNotificationsEnabledFilterChange(event.target.checked)}
              disabled={busy}
            />
            Notifications enabled only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={negRiskFilter}
              onChange={(event) => onNegRiskFilterChange(event.target.checked)}
              disabled={busy}
            />
            Neg risk only
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={rewardsHasRatesFilter}
              onChange={(event) => onRewardsHasRatesFilterChange(event.target.checked)}
              disabled={busy}
            />
            Rewards has rates only
          </label>
        </div>

        <div className="filter-grid">
          <label>
            Minimum order size min
            <input
              type="number"
              min={0}
              step="any"
              value={minimumOrderSizeMinInput}
              onChange={(event) => onMinimumOrderSizeMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 10"
            />
          </label>

          <label>
            Minimum order size max
            <input
              type="number"
              min={0}
              step="any"
              value={minimumOrderSizeMaxInput}
              onChange={(event) => onMinimumOrderSizeMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 1000"
            />
          </label>

          <label>
            Minimum tick size min
            <input
              type="number"
              min={0}
              step="any"
              value={minimumTickSizeMinInput}
              onChange={(event) => onMinimumTickSizeMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0.01"
            />
          </label>

          <label>
            Minimum tick size max
            <input
              type="number"
              min={0}
              step="any"
              value={minimumTickSizeMaxInput}
              onChange={(event) => onMinimumTickSizeMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 1"
            />
          </label>
        </div>

        <div className="filter-grid">
          <label>
            Maker base fee min
            <input
              type="number"
              min={0}
              step="any"
              value={makerBaseFeeMinInput}
              onChange={(event) => onMakerBaseFeeMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0.01"
            />
          </label>

          <label>
            Maker base fee max
            <input
              type="number"
              min={0}
              step="any"
              value={makerBaseFeeMaxInput}
              onChange={(event) => onMakerBaseFeeMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0.1"
            />
          </label>

          <label>
            Taker base fee min
            <input
              type="number"
              min={0}
              step="any"
              value={takerBaseFeeMinInput}
              onChange={(event) => onTakerBaseFeeMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0.01"
            />
          </label>

          <label>
            Taker base fee max
            <input
              type="number"
              min={0}
              step="any"
              value={takerBaseFeeMaxInput}
              onChange={(event) => onTakerBaseFeeMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0.1"
            />
          </label>
        </div>

        <div className="filter-grid">
          <label>
            Rewards min size min
            <input
              type="number"
              min={0}
              step="any"
              value={rewardsMinSizeMinInput}
              onChange={(event) => onRewardsMinSizeMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0.5"
            />
          </label>

          <label>
            Rewards min size max
            <input
              type="number"
              min={0}
              step="any"
              value={rewardsMinSizeMaxInput}
              onChange={(event) => onRewardsMinSizeMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 10"
            />
          </label>

          <label>
            Rewards max spread min
            <input
              type="number"
              min={0}
              step="any"
              value={rewardsMaxSpreadMinInput}
              onChange={(event) => onRewardsMaxSpreadMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0.01"
            />
          </label>

          <label>
            Rewards max spread max
            <input
              type="number"
              min={0}
              step="any"
              value={rewardsMaxSpreadMaxInput}
              onChange={(event) => onRewardsMaxSpreadMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 1"
            />
          </label>
        </div>

        <div className="filter-grid">
          <label>
            Seconds delay min
            <input
              type="number"
              min={0}
              step="any"
              value={secondsDelayMinInput}
              onChange={(event) => onSecondsDelayMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 0"
            />
          </label>

          <label>
            Seconds delay max
            <input
              type="number"
              min={0}
              step="any"
              value={secondsDelayMaxInput}
              onChange={(event) => onSecondsDelayMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 3600"
            />
          </label>

          <label>
            Accepting order ts min
            <input
              type="number"
              min={0}
              step="any"
              value={acceptingOrderTimestampMinInput}
              onChange={(event) => onAcceptingOrderTimestampMinInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 1730000000000"
            />
          </label>

          <label>
            Accepting order ts max
            <input
              type="number"
              min={0}
              step="any"
              value={acceptingOrderTimestampMaxInput}
              onChange={(event) => onAcceptingOrderTimestampMaxInputChange(event.target.value)}
              disabled={busy}
              placeholder="e.g. 1730000001000"
            />
          </label>
        </div>

        <div className="filter-grid">
          <label>
            End date min
            <input
              type="datetime-local"
              value={endDateIsoMinInput}
              onChange={(event) => onEndDateIsoMinInputChange(event.target.value)}
              disabled={busy}
            />
          </label>

          <label>
            End date max
            <input
              type="datetime-local"
              value={endDateIsoMaxInput}
              onChange={(event) => onEndDateIsoMaxInputChange(event.target.value)}
              disabled={busy}
            />
          </label>

          <label>
            Game start min
            <input
              type="datetime-local"
              value={gameStartTimeMinInput}
              onChange={(event) => onGameStartTimeMinInputChange(event.target.value)}
              disabled={busy}
            />
          </label>

          <label>
            Game start max
            <input
              type="datetime-local"
              value={gameStartTimeMaxInput}
              onChange={(event) => onGameStartTimeMaxInputChange(event.target.value)}
              disabled={busy}
            />
          </label>
        </div>

        <label>
          Tags (comma separated)
          <input
            value={tagsInput}
            onChange={(event) => onTagsInputChange(event.target.value)}
            disabled={busy}
            placeholder="Politics, Crypto, Sports"
          />
        </label>

        <label>
          Question contains
          <input
            value={questionContainsInput}
            onChange={(event) => onQuestionContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. election, trump"
          />
        </label>

        <label>
          Market slug contains
          <input
            value={marketSlugContainsInput}
            onChange={(event) => onMarketSlugContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. climate"
          />
        </label>

        <label>
          Question ID contains
          <input
            value={questionIdContainsInput}
            onChange={(event) => onQuestionIdContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. 0x1234"
          />
        </label>

        <label>
          Description contains
          <input
            value={descriptionContainsInput}
            onChange={(event) => onDescriptionContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. Senate, FIFA"
          />
        </label>

        <label>
          Condition ID contains
          <input
            value={conditionIdContainsInput}
            onChange={(event) => onConditionIdContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="condition id fragment"
          />
        </label>

        <label>
          Icon contains
          <input
            value={iconContainsInput}
            onChange={(event) => onIconContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. https://...png"
          />
        </label>

        <label>
          Image contains
          <input
            value={imageContainsInput}
            onChange={(event) => onImageContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. https://...jpg"
          />
        </label>

        <label>
          FPMM contains
          <input
            value={fpmmContainsInput}
            onChange={(event) => onFpmmContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="FPMM value"
          />
        </label>

        <label>
          Neg-risk market ID contains
          <input
            value={negRiskMarketIdContainsInput}
            onChange={(event) => onNegRiskMarketIdContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. 123"
          />
        </label>

        <label>
          Neg-risk request ID contains
          <input
            value={negRiskRequestIdContainsInput}
            onChange={(event) => onNegRiskRequestIdContainsInputChange(event.target.value)}
            disabled={busy}
            placeholder="e.g. req_123"
          />
        </label>
      </fieldset>

      <label>
        WebSocket URL (optional)
        <input
          value={wsUrlInput}
          onChange={(event) => onWsUrlChange(event.target.value)}
          disabled={busy}
          placeholder="wss://... (optional)"
        />
      </label>
      <label>
        WebSocket connect timeout ms (optional)
        <input
          type="number"
          min={1}
          step={1}
          value={wsConnectTimeoutMsInput}
          onChange={(event) => onWsConnectTimeoutMsChange(event.target.value)}
          disabled={busy}
          placeholder="e.g. 12000"
        />
      </label>
      <label>
        WebSocket chunk size (optional)
        <input
          type="number"
          min={1}
          step={1}
          value={wsChunkSizeInput}
          onChange={(event) => onWsChunkSizeChange(event.target.value)}
          disabled={busy}
          placeholder="e.g. 50"
        />
      </label>
      <label>
        Market fetch timeout ms (optional)
        <input
          type="number"
          min={1}
          step={1}
          value={marketFetchTimeoutMsInput}
          onChange={(event) => onMarketFetchTimeoutMsChange(event.target.value)}
          disabled={busy}
          placeholder="e.g. 12000"
        />
      </label>

      <div className="button-row">
        <button type="submit" disabled={busy || disabled}>
          {busy ? "Starting…" : "Start discovery"}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={onPreview}
          disabled={busy || disabled || previewing}
        >
          {previewing ? "Running preview…" : "Preview sample"}
        </button>

        {busy ? (
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}
