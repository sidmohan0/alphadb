import { AlphaDBMarketStream } from "@alphadb/sdk";

import { backendClient } from "../api/backend.js";

export class BackendMarketStream {
  private readonly stream: AlphaDBMarketStream;

  constructor(options: { onStatus: (message: string) => void; onTicker: (payload: Record<string, unknown>) => void }) {
    this.stream = backendClient.createMarketStream(options);
  }

  getStatusReason(): string | null {
    return this.stream.getStatusReason();
  }

  replaceMarkets(nextTickers: string[]): void {
    this.stream.replaceMarkets(nextTickers);
  }

  close(): void {
    this.stream.close();
  }
}
