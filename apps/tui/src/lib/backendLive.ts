import { backendApiBaseUrl } from "../api/backend.js";

type StatusHandler = (message: string) => void;
type TickerHandler = (payload: Record<string, unknown>) => void;

interface BackendMarketStreamOptions {
  onStatus: StatusHandler;
  onTicker: TickerHandler;
}

function sameTickers(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false;
  }

  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return false;
    }
  }

  return true;
}

export class BackendMarketStream {
  private readonly onStatus: StatusHandler;
  private readonly onTicker: TickerHandler;
  private readonly baseUrl: string | null;
  private controller: AbortController | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private reconnectDelayMs = 1_000;
  private closed = false;
  private tickers: string[] = [];

  constructor(options: BackendMarketStreamOptions) {
    this.onStatus = options.onStatus;
    this.onTicker = options.onTicker;
    this.baseUrl = backendApiBaseUrl();
  }

  getStatusReason(): string | null {
    return this.baseUrl ? null : "set ALPHADB_API_BASE_URL to enable backend streaming";
  }

  replaceMarkets(nextTickers: string[]): void {
    const normalized = [...new Set(nextTickers.filter(Boolean))].sort();
    if (sameTickers(normalized, this.tickers)) {
      return;
    }

    this.tickers = normalized;
    this.restart();
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.controller?.abort();
    this.controller = null;
  }

  private restart(): void {
    if (this.closed) {
      return;
    }

    if (!this.baseUrl) {
      this.onStatus("backend stream unavailable");
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.controller?.abort();
    this.controller = null;

    if (this.tickers.length === 0) {
      this.onStatus("backend stream idle");
      return;
    }

    const controller = new AbortController();
    this.controller = controller;
    void this.connect(controller);
  }

  private async connect(controller: AbortController): Promise<void> {
    if (!this.baseUrl) {
      return;
    }

    try {
      const url = new URL(`${this.baseUrl}/markets/stream`);
      url.searchParams.set("tickers", this.tickers.join(","));

      const response = await fetch(url.toString(), {
        headers: {
          Accept: "text/event-stream",
          "X-AlphaDB-User-Id": process.env.ALPHADB_USER_ID?.trim() || "local-user",
        },
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      this.onStatus(`backend stream connected (${this.tickers.length} markets)`);
      this.reconnectDelayMs = 1_000;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!controller.signal.aborted) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          this.handleFrame(frame);
        }
      }
    } catch (error) {
      if (controller.signal.aborted || this.closed) {
        return;
      }

      this.onStatus(error instanceof Error ? `backend stream reconnecting: ${error.message}` : "backend stream reconnecting");
    }

    if (this.closed || controller.signal.aborted) {
      return;
    }

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.restart();
    }, this.reconnectDelayMs);
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 15_000);
  }

  private handleFrame(frame: string): void {
    const lines = frame.split("\n");
    let event = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (!line || line.startsWith(":")) {
        continue;
      }

      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim();
        continue;
      }

      if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trim());
      }
    }

    if (dataLines.length === 0) {
      return;
    }

    try {
      const payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      if (event === "status" && typeof payload.message === "string") {
        this.onStatus(payload.message);
        return;
      }

      if (event === "ticker") {
        this.onTicker(payload);
      }
    } catch {
      this.onStatus("backend stream parse error");
    }
  }
}
