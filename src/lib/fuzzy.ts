import { MarketSummary } from "../types.js";

export interface SearchRankOptions {
  limit: number;
  remoteIds?: Set<string>;
  savedIds?: Set<string>;
  recentIds?: Set<string>;
}

function normalize(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function compact(value: string): string {
  return normalize(value).replace(/\s+/g, "");
}

function subsequenceScore(query: string, target: string): number {
  if (!query || !target) {
    return 0;
  }

  let queryIndex = 0;
  let streak = 0;
  let score = 0;

  for (let index = 0; index < target.length && queryIndex < query.length; index += 1) {
    if (target[index] !== query[queryIndex]) {
      streak = 0;
      continue;
    }

    streak += 1;
    score += 2 + streak * 3;
    queryIndex += 1;
  }

  if (queryIndex !== query.length) {
    return 0;
  }

  return score + Math.max(0, 25 - (target.length - query.length));
}

function scoreField(query: string, tokens: string[], rawField: string | null | undefined): number {
  if (!rawField) {
    return 0;
  }

  const field = normalize(rawField);
  if (!field) {
    return 0;
  }

  const compactField = compact(rawField);
  const compactQuery = query.replace(/\s+/g, "");
  let score = 0;

  if (field === query) {
    score += 240;
  }

  if (field.startsWith(query)) {
    score += 150;
  } else if (field.includes(query)) {
    score += 100;
  }

  let matchedTokens = 0;
  for (const token of tokens) {
    if (field.startsWith(token)) {
      score += 45;
      matchedTokens += 1;
      continue;
    }

    if (field.includes(token)) {
      score += 24;
      matchedTokens += 1;
    }
  }

  if (matchedTokens === tokens.length && tokens.length > 0) {
    score += 55;
  }

  score += subsequenceScore(compactQuery, compactField);

  return score;
}

function marketScore(
  query: string,
  tokens: string[],
  market: MarketSummary,
  options: SearchRankOptions,
): number {
  const scores = [
    scoreField(query, tokens, market.question) * 1.3,
    scoreField(query, tokens, market.eventTitle) * 1.05,
    scoreField(query, tokens, market.seriesTitle),
    scoreField(query, tokens, market.slug),
    ...market.outcomes.map((outcome) => scoreField(query, tokens, outcome.name) * 0.9),
  ];

  let score = Math.max(...scores, 0);
  if (score <= 0) {
    return 0;
  }

  if (options.remoteIds?.has(market.id)) {
    score += 35;
  }

  if (options.savedIds?.has(market.id)) {
    score += 18;
  }

  if (options.recentIds?.has(market.id)) {
    score += 10;
  }

  score += Math.min(18, Math.log10(Math.max(1, market.volume24hr + 1)) * 6);
  score += Math.min(10, Math.log10(Math.max(1, market.liquidity + 1)) * 3);

  return score;
}

export function rankMarkets(
  query: string,
  markets: MarketSummary[],
  options: SearchRankOptions,
): MarketSummary[] {
  const normalizedQuery = normalize(query);
  if (!normalizedQuery) {
    return markets.slice(0, options.limit);
  }

  const tokens = normalizedQuery.split(" ").filter(Boolean);
  const ranked = markets
    .map((market) => ({
      market,
      score: marketScore(normalizedQuery, tokens, market, options),
    }))
    .filter((entry) => entry.score > 0)
    .sort((left, right) => {
      if (right.score !== left.score) {
        return right.score - left.score;
      }

      return right.market.volume24hr - left.market.volume24hr;
    });

  return ranked.map((entry) => entry.market).slice(0, options.limit);
}
