import { type FormEvent } from "react";

interface DiscoveryLauncherProps {
  chainIdInput: string;
  wsUrlInput: string;
  onChainIdChange: (value: string) => void;
  onWsUrlChange: (value: string) => void;
  onStart: () => void;
  onCancel: () => void;
  disabled: boolean;
  busy: boolean;
}

export function DiscoveryLauncher({
  chainIdInput,
  wsUrlInput,
  onChainIdChange,
  onWsUrlChange,
  onStart,
  onCancel,
  disabled,
  busy,
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
        WebSocket URL (optional)
        <input
          value={wsUrlInput}
          onChange={(event) => onWsUrlChange(event.target.value)}
          disabled={busy}
          placeholder="wss://... (optional)"
        />
      </label>

      <div className="button-row">
        <button type="submit" disabled={busy || disabled}>
          {busy ? "Starting…" : "Start discovery"}
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
