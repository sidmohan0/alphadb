import crypto from "node:crypto";
import { readFileSync } from "node:fs";
import WS from "ws";

type StatusHandler = (message: string) => void;
type TickerHandler = (payload: Record<string, unknown>) => void;

interface KalshiTickerStreamOptions {
  onStatus: StatusHandler;
  onTicker: TickerHandler;
}

interface KalshiAuthMaterial {
  apiKeyId: string;
  privateKeyPem: string;
  wsUrl: string;
}

function loadAuthMaterial(): KalshiAuthMaterial | { error: string } {
  const apiKeyId = process.env.KALSHI_API_KEY_ID?.trim();
  const privateKeyPemEnv = process.env.KALSHI_PRIVATE_KEY_PEM?.trim();
  const privateKeyPath = process.env.KALSHI_PRIVATE_KEY_PATH?.trim();
  const wsUrl = process.env.KALSHI_WS_URL?.trim() || "wss://api.elections.kalshi.com/trade-api/ws/v2";

  if (!apiKeyId) {
    return { error: "set KALSHI_API_KEY_ID to enable Kalshi live ticker updates" };
  }

  let privateKeyPem = privateKeyPemEnv;
  if (!privateKeyPem && privateKeyPath) {
    privateKeyPem = readFileSync(privateKeyPath, "utf8");
  }

  if (!privateKeyPem) {
    return { error: "set KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM to enable Kalshi live ticker updates" };
  }

  return {
    apiKeyId,
    privateKeyPem,
    wsUrl,
  };
}

function createAuthHeaders(material: KalshiAuthMaterial): Record<string, string> {
  const timestamp = String(Date.now());
  const message = `${timestamp}GET/trade-api/ws/v2`;
  const signature = crypto.sign("RSA-SHA256", Buffer.from(message), {
    key: material.privateKeyPem,
    padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
    saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
  }).toString("base64");

  return {
    "KALSHI-ACCESS-KEY": material.apiKeyId,
    "KALSHI-ACCESS-SIGNATURE": signature,
    "KALSHI-ACCESS-TIMESTAMP": timestamp,
  };
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

export class KalshiTickerStream {
  private readonly onStatus: StatusHandler;
  private readonly onTicker: TickerHandler;
  private socket: WS | null = null;
  private closed = false;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private tickers: string[] = [];
  private reconnectDelayMs = 1_000;
  private readonly authMaterial: KalshiAuthMaterial | null;
  private readonly authError: string | null;

  constructor(options: KalshiTickerStreamOptions) {
    this.onStatus = options.onStatus;
    this.onTicker = options.onTicker;

    const material = loadAuthMaterial();
    if ("error" in material) {
      this.authMaterial = null;
      this.authError = material.error;
    } else {
      this.authMaterial = material;
      this.authError = null;
    }
  }

  getStatusReason(): string | null {
    return this.authError;
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

    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.close();
      this.socket = null;
    }
  }

  private restart(): void {
    if (this.closed) {
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (!this.authMaterial) {
      this.onStatus(this.authError ?? "Kalshi live ticker unavailable");
      return;
    }

    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.terminate();
      this.socket = null;
    }

    if (this.tickers.length === 0) {
      this.onStatus("Kalshi live idle");
      return;
    }

    const headers = createAuthHeaders(this.authMaterial);
    this.socket = new WS(this.authMaterial.wsUrl, {
      headers,
    });

    this.socket.on("open", () => {
      this.onStatus(`Kalshi live connected (${this.tickers.length} markets)`);
      this.reconnectDelayMs = 1_000;
      this.socket?.send(JSON.stringify({
        id: Date.now(),
        cmd: "subscribe",
        params: {
          channels: ["ticker"],
          market_tickers: this.tickers,
        },
      }));
    });

    this.socket.on("message", (raw: WS.RawData) => {
      try {
        const payload = JSON.parse(String(raw)) as Record<string, unknown>;
        if (payload.type === "ticker" && payload.msg && typeof payload.msg === "object") {
          this.onTicker(payload.msg as Record<string, unknown>);
        }
      } catch {
        this.onStatus("Kalshi live message parse error");
      }
    });

    this.socket.on("error", () => {
      this.onStatus("Kalshi live socket error");
    });

    this.socket.on("close", () => {
      this.socket = null;
      if (this.closed) {
        return;
      }

      this.onStatus(`Kalshi live reconnecting in ${Math.round(this.reconnectDelayMs / 1000)}s`);
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.restart();
      }, this.reconnectDelayMs);
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 15_000);
    });
  }
}
