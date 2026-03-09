import crypto from "node:crypto";
import { readFileSync } from "node:fs";
import WS from "ws";

type StatusListener = (message: string) => void;
type TickerListener = (payload: Record<string, unknown>) => void;

interface KalshiAuthMaterial {
  apiKeyId: string;
  privateKeyPem: string;
  wsUrl: string;
}

interface Subscriber {
  tickers: Set<string>;
  onStatus: StatusListener;
  onTicker: TickerListener;
}

function loadAuthMaterial(): KalshiAuthMaterial | { error: string } {
  const apiKeyId = process.env.KALSHI_API_KEY_ID?.trim();
  const privateKeyPemEnv = process.env.KALSHI_PRIVATE_KEY_PEM?.trim();
  const privateKeyPath = process.env.KALSHI_PRIVATE_KEY_PATH?.trim();
  const wsUrl = process.env.KALSHI_WS_URL?.trim() || "wss://api.elections.kalshi.com/trade-api/ws/v2";

  if (!apiKeyId) {
    return { error: "set KALSHI_API_KEY_ID to enable backend Kalshi streaming" };
  }

  let privateKeyPem = privateKeyPemEnv;
  if (!privateKeyPem && privateKeyPath) {
    privateKeyPem = readFileSync(privateKeyPath, "utf8");
  }

  if (!privateKeyPem) {
    return { error: "set KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM to enable backend Kalshi streaming" };
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

class KalshiRealtimeHub {
  private readonly authMaterial: KalshiAuthMaterial | null;
  private readonly authError: string | null;
  private readonly subscribers = new Map<number, Subscriber>();
  private nextSubscriberId = 1;
  private socket: WS | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private reconnectDelayMs = 1_000;
  private currentStatus = "Kalshi stream idle";

  constructor() {
    const material = loadAuthMaterial();
    if ("error" in material) {
      this.authMaterial = null;
      this.authError = material.error;
      this.currentStatus = material.error;
    } else {
      this.authMaterial = material;
      this.authError = null;
    }
  }

  subscribe(
    tickers: string[],
    onStatus: StatusListener,
    onTicker: TickerListener,
  ): { close: () => void; updateTickers: (nextTickers: string[]) => void; getStatus: () => string } {
    const id = this.nextSubscriberId++;
    this.subscribers.set(id, {
      tickers: new Set(tickers.filter(Boolean)),
      onStatus,
      onTicker,
    });

    onStatus(this.currentStatus);
    this.restart();

    return {
      close: () => {
        this.subscribers.delete(id);
        this.restart();
      },
      updateTickers: (nextTickers: string[]) => {
        const subscriber = this.subscribers.get(id);
        if (!subscriber) {
          return;
        }

        subscriber.tickers = new Set(nextTickers.filter(Boolean));
        this.restart();
      },
      getStatus: () => this.currentStatus,
    };
  }

  private activeTickers(): string[] {
    return [...new Set(
      [...this.subscribers.values()].flatMap((subscriber) => [...subscriber.tickers]),
    )].sort();
  }

  private broadcastStatus(message: string): void {
    this.currentStatus = message;
    for (const subscriber of this.subscribers.values()) {
      subscriber.onStatus(message);
    }
  }

  private restart(): void {
    if (!this.authMaterial) {
      this.broadcastStatus(this.authError ?? "Kalshi stream unavailable");
      return;
    }

    const tickers = this.activeTickers();
    if (tickers.length === 0) {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
      if (this.socket) {
        this.socket.removeAllListeners();
        this.socket.close();
        this.socket = null;
      }
      this.broadcastStatus("Kalshi stream idle");
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.terminate();
      this.socket = null;
    }

    const headers = createAuthHeaders(this.authMaterial);
    this.socket = new WS(this.authMaterial.wsUrl, { headers });
    this.socket.on("open", () => {
      this.broadcastStatus(`Kalshi backend stream connected (${tickers.length} markets)`);
      this.reconnectDelayMs = 1_000;
      this.socket?.send(JSON.stringify({
        id: Date.now(),
        cmd: "subscribe",
        params: {
          channels: ["ticker"],
          market_tickers: tickers,
        },
      }));
    });

    this.socket.on("message", (raw: WS.RawData) => {
      try {
        const payload = JSON.parse(String(raw)) as Record<string, unknown>;
        if (payload.type !== "ticker" || !payload.msg || typeof payload.msg !== "object") {
          return;
        }

        const msg = payload.msg as Record<string, unknown>;
        const marketTicker = typeof msg.market_ticker === "string" ? msg.market_ticker : null;
        if (!marketTicker) {
          return;
        }

        for (const subscriber of this.subscribers.values()) {
          if (subscriber.tickers.has(marketTicker)) {
            subscriber.onTicker(msg);
          }
        }
      } catch {
        this.broadcastStatus("Kalshi backend stream parse error");
      }
    });

    this.socket.on("error", () => {
      this.broadcastStatus("Kalshi backend stream socket error");
    });

    this.socket.on("close", () => {
      this.socket = null;
      if (this.activeTickers().length === 0) {
        this.broadcastStatus("Kalshi stream idle");
        return;
      }

      this.broadcastStatus(`Kalshi backend stream reconnecting in ${Math.round(this.reconnectDelayMs / 1000)}s`);
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.restart();
      }, this.reconnectDelayMs);
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 15_000);
    });
  }
}

export const kalshiRealtimeHub = new KalshiRealtimeHub();
