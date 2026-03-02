import { Redis } from "ioredis";

let redisClient: Redis | null = null;

export function getRedisUrl(): string {
  const redisUrl = process.env.REDIS_URL;
  if (!redisUrl) {
    throw new Error("REDIS_URL is required for discovery cache/locks");
  }

  return redisUrl;
}

export function getRedisClient(): Redis {
  if (!redisClient) {
    const url = getRedisUrl();
    redisClient = new Redis(url);
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
