import { DiscoveryRunReadModel } from "../../types";
import { getRedisClient } from "./redis";

export interface DiscoveryRunCache {
  getLatestRunId(scope: string): Promise<string | null>;
  setLatestRunId(scope: string, runId: string, ttlSec: number): Promise<void>;

  getCachedRun(runId: string): Promise<DiscoveryRunReadModel | null>;
  setCachedRun(runId: string, payload: DiscoveryRunReadModel, ttlSec: number): Promise<void>;
  clearCachedRun(runId: string): Promise<void>;

  getActiveRunIdByDedupeKey(dedupeKey: string): Promise<string | null>;
  setActiveRunIdByDedupeKey(dedupeKey: string, runId: string, ttlSec: number): Promise<boolean>;
  deleteActiveRunIdByDedupeKey(dedupeKey: string): Promise<void>;

  acquireSlot(semaphoreKey: string, limit: number, ttlSec: number): Promise<{ ok: boolean; active: number; limit: number }>;
  releaseSlot(semaphoreKey: string): Promise<void>;
}

interface InMemoryCacheEntry<T> {
  value: T;
  expiresAt: number | null;
}

class InMemoryDiscoveryRunCache implements DiscoveryRunCache {
  private latest = new Map<string, InMemoryCacheEntry<string>>();
  private runs = new Map<string, InMemoryCacheEntry<DiscoveryRunReadModel>>();
  private dedupe = new Map<string, InMemoryCacheEntry<string>>();
  private slots = new Map<string, number>();

  private now(): number {
    return Date.now();
  }

  private isExpired(entry: InMemoryCacheEntry<unknown> | undefined): boolean {
    if (!entry) return true;
    return entry.expiresAt !== null && entry.expiresAt <= this.now();
  }

  private setWithTTL<T>(key: string, map: Map<string, InMemoryCacheEntry<T>>, value: T, ttlSec?: number): void {
    map.set(key, {
      value,
      expiresAt: ttlSec ? this.now() + ttlSec * 1000 : null,
    });
  }

  private getWithTTL<T>(key: string, map: Map<string, InMemoryCacheEntry<T>>): T | null {
    const entry = map.get(key);
    if (!entry || this.isExpired(entry)) {
      map.delete(key);
      return null;
    }

    return entry.value;
  }

  async getLatestRunId(scope: string): Promise<string | null> {
    return this.getWithTTL(scope, this.latest);
  }

  async setLatestRunId(scope: string, runId: string, ttlSec: number): Promise<void> {
    this.setWithTTL(scope, this.latest, runId, ttlSec);
  }

  async getCachedRun(runId: string): Promise<DiscoveryRunReadModel | null> {
    return this.getWithTTL(`run:${runId}`, this.runs);
  }

  async setCachedRun(runId: string, payload: DiscoveryRunReadModel, ttlSec: number): Promise<void> {
    this.setWithTTL(`run:${runId}`, this.runs, payload, ttlSec);
  }

  async clearCachedRun(runId: string): Promise<void> {
    this.runs.delete(`run:${runId}`);
  }

  async getActiveRunIdByDedupeKey(dedupeKey: string): Promise<string | null> {
    return this.getWithTTL(`dedupe:${dedupeKey}`, this.dedupe);
  }

  async setActiveRunIdByDedupeKey(dedupeKey: string, runId: string, ttlSec: number): Promise<boolean> {
    const key = `dedupe:${dedupeKey}`;
    const existing = this.dedupe.get(key);
    if (existing && !this.isExpired(existing)) {
      return false;
    }

    this.setWithTTL(key, this.dedupe, runId, ttlSec);
    return true;
  }

  async deleteActiveRunIdByDedupeKey(dedupeKey: string): Promise<void> {
    this.dedupe.delete(`dedupe:${dedupeKey}`);
  }

  async acquireSlot(semaphoreKey: string, limit: number, ttlSec: number): Promise<{ ok: boolean; active: number; limit: number }> {
    const key = `slot:${semaphoreKey}`;
    const current = this.slots.get(key) ?? 0;

    if (current + 1 > limit) {
      return { ok: false, active: current, limit };
    }

    this.slots.set(key, current + 1);
    return { ok: true, active: current + 1, limit };
  }

  async releaseSlot(semaphoreKey: string): Promise<void> {
    const key = `slot:${semaphoreKey}`;
    const current = this.slots.get(key) ?? 0;
    if (current <= 1) {
      this.slots.delete(key);
    } else {
      this.slots.set(key, current - 1);
    }
  }
}

class RedisDiscoveryRunCache implements DiscoveryRunCache {
  private keyLatest(scope: string): string {
    return `pm:discovery:latest:${scope}`;
  }

  private keyRun(runId: string): string {
    return `pm:discovery:run:${runId}`;
  }

  private keyActiveDedupe(dedupeKey: string): string {
    return `pm:discovery:active:${dedupeKey}`;
  }

  private keySlot(scope: string): string {
    return `pm:discovery:slot:${scope}`;
  }

  async getLatestRunId(scope: string): Promise<string | null> {
    const redis = getRedisClient();
    return redis.get(this.keyLatest(scope));
  }

  async setLatestRunId(scope: string, runId: string, ttlSec: number): Promise<void> {
    const redis = getRedisClient();
    await (redis as unknown as any).set(this.keyLatest(scope), runId, "EX", Math.max(1, ttlSec));
  }

  async getCachedRun(runId: string): Promise<DiscoveryRunReadModel | null> {
    const redis = getRedisClient();
    const raw = await redis.get(this.keyRun(runId));
    if (!raw) {
      return null;
    }

    return JSON.parse(raw) as DiscoveryRunReadModel;
  }

  async setCachedRun(runId: string, payload: DiscoveryRunReadModel, ttlSec: number): Promise<void> {
    const redis = getRedisClient();
    await (redis as unknown as any).set(this.keyRun(runId), JSON.stringify(payload), "EX", Math.max(1, ttlSec));
  }

  async clearCachedRun(runId: string): Promise<void> {
    const redis = getRedisClient();
    await redis.del(this.keyRun(runId));
  }

  async getActiveRunIdByDedupeKey(dedupeKey: string): Promise<string | null> {
    const redis = getRedisClient();
    return redis.get(this.keyActiveDedupe(dedupeKey));
  }

  async setActiveRunIdByDedupeKey(dedupeKey: string, runId: string, ttlSec: number): Promise<boolean> {
    const redis = getRedisClient();
    const key = this.keyActiveDedupe(dedupeKey);
    const result = await (redis as unknown as any).set(key, runId, "NX", "EX", Math.max(1, ttlSec));
    return result === "OK";
  }

  async deleteActiveRunIdByDedupeKey(dedupeKey: string): Promise<void> {
    const redis = getRedisClient();
    await redis.del(this.keyActiveDedupe(dedupeKey));
  }

  async acquireSlot(semaphoreKey: string, limit: number, ttlSec: number): Promise<{ ok: boolean; active: number; limit: number }> {
    const redis = getRedisClient();
    const key = this.keySlot(semaphoreKey);
    const active = await redis.incr(key);

    if (active === 1) {
      await redis.expire(key, Math.max(1, ttlSec));
    }

    if (active > limit) {
      await redis.decr(key);
      return { ok: false, active, limit };
    }

    return { ok: true, active, limit };
  }

  async releaseSlot(semaphoreKey: string): Promise<void> {
    const redis = getRedisClient();
    const key = this.keySlot(semaphoreKey);
    const active = await redis.decr(key);
    if (active <= 0) {
      await redis.del(key);
    }
  }
}

export function createDiscoveryRunCache(useInMemoryFallback = true): DiscoveryRunCache {
  if (!process.env.REDIS_URL) {
    if (useInMemoryFallback) {
      return new InMemoryDiscoveryRunCache();
    }

    throw new Error("REDIS_URL is required for discovery run cache/locks");
  }

  return new RedisDiscoveryRunCache();
}
