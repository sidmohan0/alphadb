import { runPolymarketMarketChannels } from "./polymarket/cli/runMarketChannels";

runPolymarketMarketChannels().catch((error: unknown) => {
  console.error("Failed to discover market channels:", error);
  process.exit(1);
});
