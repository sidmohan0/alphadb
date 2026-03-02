import { Redis, type RedisOptions } from "ioredis";

let redisClient: Redis | null = null;

function parseIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function getRedisUrl(): string {
  const redisUrl = process.env.REDIS_URL;
  if (!redisUrl) {
    throw new Error("REDIS_URL is required for discovery cache/locks");
  }

  return redisUrl;
}

function parseBooleanEnv(name: string, fallback = false): boolean {
  const value = process.env[name];
  if (value === undefined) {
    return fallback;
  }

  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

export function getRedisClient(): Redis {
  if (!redisClient) {
    const url = getRedisUrl();
    const retryBaseMs = parseIntEnv("REDIS_RETRY_BASE_MS", 100);
    const retryMaxMs = parseIntEnv("REDIS_RETRY_MAX_MS", 2000);
    const maxRetriesPerRequest = parseIntEnv("REDIS_MAX_RETRIES_PER_REQUEST", 3);

    const options: RedisOptions = {
      connectTimeout: parseIntEnv("REDIS_CONNECT_TIMEOUT_MS", 2000),
      commandTimeout: parseIntEnv("REDIS_COMMAND_TIMEOUT_MS", 5000),
      maxRetriesPerRequest,
      retryStrategy: (times: number) => {
        const capped = Math.min(times * retryBaseMs, retryMaxMs);
        return capped;
      },
      enableOfflineQueue: true,
      lazyConnect: false,
      reconnectOnError: (error: Error) => {
        const shouldReconnect = parseBooleanEnv("REDIS_RECONNECT_ON_ERROR", true);
        if (!shouldReconnect) {
          return false;
        }

        const message = error.message.toLowerCase();
        return message.includes("read") || message.includes("write") || message.includes("reset") || message.includes("timeout");
      },
    };

    redisClient = new Redis(url, options);
  }

  return redisClient;
}

export async function closeRedisClient(): Promise<void> {
  if (!redisClient) {
    return;
  }

  await redisClient.quit();
  redisClient = null;
}
