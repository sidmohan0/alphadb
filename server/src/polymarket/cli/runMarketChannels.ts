import {
  DEFAULT_CLOB_API_URL,
  DEFAULT_CHAIN_ID,
  DEFAULT_WS_CHUNK_SIZE,
  DEFAULT_WS_CONNECT_TIMEOUT_MS,
  DEFAULT_MARKET_FETCH_TIMEOUT_MS,
  type MarketChannelRunResult,
} from "../types";
import { discoverMarketChannels } from "../services/marketChannelDiscoveryService";
import { parseNumber } from "../utils";

function renderHumanOutput(result: MarketChannelRunResult): void {
  console.log(`\n=== Polymarket market channels ===`);
  console.log(`Markets returned: ${result.source.marketCount}`);
  console.log(`Unique market channels found: ${result.channels.length}`);
  console.log(`Connected to websocket: ${result.wsScan?.connected ? "yes" : "no"}`);

  if (result.wsScan) {
    console.log(`WS observed channels: ${result.wsScan.observedChannels.length}`);
    if (result.wsScan.errors.length > 0) {
      console.log("WS probe notes:");
      for (const message of result.wsScan.errors) {
        console.log(`- ${message}`);
      }
    }
  } else {
    console.log("Set WS_URL to run live websocket probe.");
  }

  console.log("\nChannel list:");
  for (const channel of result.channels) {
    const label = [channel.conditionId, channel.assetId, channel.marketSlug, channel.outcome]
      .filter(Boolean)
      .join(" | ");
    console.log(`- ${label}`);
  }
}

/**
 * CLI entrypoint for market channel discovery.
 */
export async function runPolymarketMarketChannels(): Promise<void> {
  const clobApiUrl = process.env.CLOB_API_URL || DEFAULT_CLOB_API_URL;
  const chainId = parseNumber(process.env.CHAIN_ID, DEFAULT_CHAIN_ID);
  const wsUrl = process.env.WS_URL;
  const wsConnectTimeoutMs = parseNumber(process.env.WS_CONNECT_TIMEOUT_MS, DEFAULT_WS_CONNECT_TIMEOUT_MS);
  const wsChunkSize = parseNumber(process.env.WS_CHUNK_SIZE, DEFAULT_WS_CHUNK_SIZE);
  const marketFetchTimeoutMs = parseNumber(process.env.MARKET_FETCH_TIMEOUT_MS, DEFAULT_MARKET_FETCH_TIMEOUT_MS);
  const emitJson = process.argv.includes("--json") || process.argv.includes("-j");

  if (emitJson) {
    console.log(`Fetching markets from ${clobApiUrl}...`);
  }

  const result = await discoverMarketChannels({
    clobApiUrl,
    chainId,
    wsUrl,
    wsConnectTimeoutMs,
    wsChunkSize,
    marketFetchTimeoutMs,
  });

  if (emitJson) {
    if (wsUrl) {
      console.log(`Probing websocket at ${wsUrl} with ${result.channels.length} channel subscriptions...`);
    }

    console.log(JSON.stringify(result, null, 2));
    return;
  }

  renderHumanOutput(result);
}
