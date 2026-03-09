import { AlphaDBMarketStream } from "@alphadb/sdk";

import { backendClient } from "../api/backend.js";
import { MarketStreamStatus, MarketStreamSubscription, MarketStreamUpdate } from "../types.js";

export class BackendMarketStream {
  private readonly stream: AlphaDBMarketStream;

  constructor(options: {
    onStatus: (status: MarketStreamStatus) => void;
    onUpdate: (payload: MarketStreamUpdate) => void;
  }) {
    this.stream = backendClient.createMarketStream(options);
  }

  getStatusReason(): string | null {
    return this.stream.getStatusReason();
  }

  replaceSubscriptions(nextSubscriptions: MarketStreamSubscription[]): void {
    this.stream.replaceSubscriptions(nextSubscriptions);
  }

  close(): void {
    this.stream.close();
  }
}
