import WS from "ws";

import type { MarketStreamSubscription, MarketStreamUpdate } from "../types";

type StatusListener = (message: string) => void;
type UpdateListener = (payload: MarketStreamUpdate) => void;

type PolymarketSubscription = MarketStreamSubscription & {
  provider: "polymarket";
};

interface Subscriber {
  subscriptions: PolymarketSubscription[];
  onStatus: StatusListener;
  onUpdate: UpdateListener;
}

interface SubscriptionBinding {
  marketId: string;
  symbol: string;
  tokenId: string;
  knownTokenIds: string[];
}

type JsonRecord = Record<string, unknown>;

const DEFAULT_POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market";

function toNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function extractEventType(payload: JsonRecord): string | null {
  const candidates = [payload.event_type, payload.eventType, payload.type];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }

  return null;
}

function extractAssetId(payload: JsonRecord): string | null {
  const candidates = [payload.asset_id, payload.assetId, payload.token_id, payload.tokenId];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }

  return null;
}

function buildOutcomePrices(
  binding: SubscriptionBinding,
  assetId: string,
  price: number | null,
): Record<string, number | null> | undefined {
  if (price === null) {
    return undefined;
  }

  const outcomePrices: Record<string, number | null> = {
    [assetId]: price,
  };

  if (binding.knownTokenIds.length === 2) {
    const otherTokenId = binding.knownTokenIds.find((tokenId) => tokenId !== assetId);
    if (otherTokenId) {
      outcomePrices[otherTokenId] = Math.max(0, 1 - price);
    }
  }

  return outcomePrices;
}

function primaryTokenId(binding: SubscriptionBinding): string {
  return binding.knownTokenIds[0] ?? binding.tokenId;
}

function isPrimaryToken(binding: SubscriptionBinding, assetId: string): boolean {
  return assetId === primaryTokenId(binding);
}

function normalizePriceForPrimary(binding: SubscriptionBinding, assetId: string, price: number | null): number | null {
  if (price === null) {
    return null;
  }

  if (isPrimaryToken(binding, assetId) || binding.knownTokenIds.length !== 2) {
    return price;
  }

  return Math.max(0, 1 - price);
}

function normalizeBidAskForPrimary(
  binding: SubscriptionBinding,
  assetId: string,
  bestBid: number | null,
  bestAsk: number | null,
): { bestBid?: number | null; bestAsk?: number | null } {
  if (isPrimaryToken(binding, assetId) || binding.knownTokenIds.length !== 2) {
    return {
      ...(bestBid !== null ? { bestBid } : {}),
      ...(bestAsk !== null ? { bestAsk } : {}),
    };
  }

  return {
    ...(bestAsk !== null ? { bestBid: Math.max(0, 1 - bestAsk) } : {}),
    ...(bestBid !== null ? { bestAsk: Math.max(0, 1 - bestBid) } : {}),
  };
}

function bestBookBid(levels: unknown): number | null {
  if (!Array.isArray(levels) || levels.length === 0) {
    return null;
  }

  return levels
    .map((entry) => toNullableNumber((entry as JsonRecord).price))
    .filter((value): value is number => value !== null)
    .reduce<number | null>((current, value) => (current === null || value > current ? value : current), null);
}

function bestBookAsk(levels: unknown): number | null {
  if (!Array.isArray(levels) || levels.length === 0) {
    return null;
  }

  return levels
    .map((entry) => toNullableNumber((entry as JsonRecord).price))
    .filter((value): value is number => value !== null)
    .reduce<number | null>((current, value) => (current === null || value < current ? value : current), null);
}

function normalizePayload(
  binding: SubscriptionBinding,
  payload: JsonRecord,
): MarketStreamUpdate | null {
  const assetId = extractAssetId(payload) ?? binding.tokenId;
  const eventType = extractEventType(payload);

  const rawPrice =
    eventType === "last_trade_price" || eventType === "price_change"
      ? toNullableNumber(payload.price) ?? toNullableNumber(payload.last_trade_price)
      : null;
  const rawBestBid =
    eventType === "book"
      ? bestBookBid(payload.bids)
      : toNullableNumber(payload.best_bid);
  const rawBestAsk =
    eventType === "book"
      ? bestBookAsk(payload.asks)
      : toNullableNumber(payload.best_ask);
  const volumeTotal =
    toNullableNumber(payload.volume) ??
    toNullableNumber(payload.volume_total) ??
    toNullableNumber(payload.dollar_volume);
  const volume24hr = toNullableNumber(payload.volume_24hr);
  const liquidity = toNullableNumber(payload.liquidity);

  if (
    eventType !== "price_change" &&
    eventType !== "last_trade_price" &&
    eventType !== "best_bid_ask" &&
    eventType !== "book"
  ) {
    return null;
  }

  const update: MarketStreamUpdate = {
    provider: "polymarket",
    marketId: binding.marketId,
    symbol: binding.symbol,
    receivedAt: Date.now(),
  };

  const { bestBid, bestAsk } = normalizeBidAskForPrimary(binding, assetId, rawBestBid, rawBestAsk);
  if ("bestBid" in { bestBid }) {
    update.bestBid = bestBid;
  }

  if ("bestAsk" in { bestAsk }) {
    update.bestAsk = bestAsk;
  }

  const price = normalizePriceForPrimary(binding, assetId, rawPrice);
  if (price !== null) {
    update.lastTradePrice = price;
    update.outcomePrices = buildOutcomePrices(binding, assetId, rawPrice);
  }

  if (typeof volumeTotal === "number") {
    update.volumeTotal = volumeTotal;
  }

  if (typeof volume24hr === "number") {
    update.volume24hr = volume24hr;
  }

  if (typeof liquidity === "number") {
    update.liquidity = liquidity;
  }

  return update;
}

class PolymarketRealtimeHub {
  private readonly subscribers = new Map<number, Subscriber>();
  private readonly socketUrl: string;
  private nextSubscriberId = 1;
  private socket: WS | null = null;
  private pingTimer: NodeJS.Timeout | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private reconnectDelayMs = 1_000;
  private currentStatus = "Polymarket stream idle";

  constructor() {
    this.socketUrl = process.env.POLYMARKET_WS_URL?.trim() || DEFAULT_POLYMARKET_WS_URL;
  }

  subscribe(
    subscriptions: PolymarketSubscription[],
    onStatus: StatusListener,
    onUpdate: UpdateListener,
  ): { close: () => void; updateSubscriptions: (nextSubscriptions: PolymarketSubscription[]) => void; getStatus: () => string } {
    const id = this.nextSubscriberId++;
    this.subscribers.set(id, {
      subscriptions,
      onStatus,
      onUpdate,
    });

    onStatus(this.currentStatus);
    this.restart();

    return {
      close: () => {
        this.subscribers.delete(id);
        this.restart();
      },
      updateSubscriptions: (nextSubscriptions: PolymarketSubscription[]) => {
        const subscriber = this.subscribers.get(id);
        if (!subscriber) {
          return;
        }

        subscriber.subscriptions = nextSubscriptions;
        this.restart();
      },
      getStatus: () => this.currentStatus,
    };
  }

  private broadcastStatus(message: string): void {
    this.currentStatus = message;
    for (const subscriber of this.subscribers.values()) {
      subscriber.onStatus(message);
    }
  }

  private activeBindings(): Map<string, SubscriptionBinding[]> {
    const bindings = new Map<string, SubscriptionBinding[]>();

    for (const subscriber of this.subscribers.values()) {
      for (const subscription of subscriber.subscriptions) {
        const tokenIds = [...new Set(subscription.outcomeTokenIds?.filter(Boolean) ?? [])];
        for (const tokenId of tokenIds) {
          const existing = bindings.get(tokenId) ?? [];
          existing.push({
            marketId: subscription.marketId,
            symbol: subscription.symbol,
            tokenId,
            knownTokenIds: tokenIds,
          });
          bindings.set(tokenId, existing);
        }
      }
    }

    return bindings;
  }

  private restart(): void {
    const bindings = this.activeBindings();

    if (bindings.size === 0) {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
      if (this.socket) {
        this.disposeSocket();
      }
      if (this.pingTimer) {
        clearInterval(this.pingTimer);
        this.pingTimer = null;
      }
      this.broadcastStatus("Polymarket stream idle");
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.socket) {
      this.disposeSocket();
    }
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }

    this.socket = new WS(this.socketUrl);
    this.socket.on("open", () => {
      const assetIds = [...bindings.keys()].sort();
      this.broadcastStatus(`Polymarket backend stream connected (${assetIds.length} assets)`);
      this.reconnectDelayMs = 1_000;
      this.socket?.send(JSON.stringify({
        type: "market",
        assets_ids: assetIds,
        initial_dump: true,
      }));
      this.pingTimer = setInterval(() => {
        if (this.socket?.readyState === WS.OPEN) {
          this.socket.send("PING");
        }
      }, 30_000);
    });

    this.socket.on("message", (raw: WS.RawData) => {
      try {
        const parsed = JSON.parse(String(raw)) as unknown;
        const messages = Array.isArray(parsed) ? parsed : [parsed];

        for (const message of messages) {
          if (!message || typeof message !== "object") {
            continue;
          }

          const payload = message as JsonRecord;
          const eventType = extractEventType(payload);
          const eventPayloads =
            eventType === "price_change" && Array.isArray(payload.price_changes)
              ? (payload.price_changes as JsonRecord[])
              : [payload];

          for (const eventPayload of eventPayloads) {
            const assetId = extractAssetId(eventPayload);
            if (!assetId) {
              continue;
            }

            const tokenBindings = bindings.get(assetId);
            if (!tokenBindings?.length) {
              continue;
            }

            const normalizedPayload = eventType === "price_change"
              ? { ...eventPayload, event_type: "price_change" }
              : eventPayload;

            for (const binding of tokenBindings) {
              const update = normalizePayload(binding, normalizedPayload);
              if (!update) {
                continue;
              }

              for (const subscriber of this.subscribers.values()) {
                if (subscriber.subscriptions.some((entry) => entry.marketId === binding.marketId)) {
                  subscriber.onUpdate(update);
                }
              }
            }
          }
        }
      } catch {
        this.broadcastStatus("Polymarket backend stream parse error");
      }
    });

    this.socket.on("error", () => {
      this.broadcastStatus("Polymarket backend stream socket error");
    });

    this.socket.on("close", () => {
      this.socket = null;
      if (this.pingTimer) {
        clearInterval(this.pingTimer);
        this.pingTimer = null;
      }
      if (this.activeBindings().size === 0) {
        this.broadcastStatus("Polymarket stream idle");
        return;
      }

      this.broadcastStatus(`Polymarket backend stream reconnecting in ${Math.round(this.reconnectDelayMs / 1000)}s`);
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.restart();
      }, this.reconnectDelayMs);
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 15_000);
    });
  }

  private disposeSocket(): void {
    if (!this.socket) {
      return;
    }

    const socket = this.socket;
    this.socket = null;
    socket.removeAllListeners();

    try {
      if (socket.readyState === WS.OPEN) {
        socket.close();
        return;
      }

      socket.terminate();
    } catch {
      // Swallow teardown errors during reconnect/cleanup.
    }
  }
}

export const polymarketRealtimeHub = new PolymarketRealtimeHub();
