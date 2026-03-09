import { getUnifiedTrendingMarkets } from "../services/marketDataService";
import { resolveUserId, saveMarketForUser, touchRecentMarketForUser } from "../services/userStateStore";

function parsePositiveInt(value: string | undefined, fallback: number): number {
  if (!value?.trim()) {
    return fallback;
  }

  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

async function main(): Promise<void> {
  const userId = resolveUserId(process.env.ALPHADB_SEED_USER_ID);
  const saveCount = parsePositiveInt(process.env.ALPHADB_SEED_SAVE_COUNT, 2);
  const recentCount = parsePositiveInt(process.env.ALPHADB_SEED_RECENT_COUNT, 4);
  const limit = Math.max(saveCount, recentCount, 4);

  const markets = await getUnifiedTrendingMarkets(limit);
  const combined = [...markets.polymarket, ...markets.kalshi];

  for (const market of combined.slice(0, saveCount)) {
    await saveMarketForUser(userId, market);
  }

  for (const market of combined.slice(0, recentCount)) {
    await touchRecentMarketForUser(userId, market);
  }

  console.log(`Seeded AlphaDB backend state for user "${userId}"`);
  console.log(`Saved markets: ${Math.min(saveCount, combined.length)}`);
  console.log(`Recent markets: ${Math.min(recentCount, combined.length)}`);
}

main().catch((error) => {
  console.error("Failed to seed backend user state", error);
  process.exit(1);
});
