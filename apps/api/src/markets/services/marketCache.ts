type CacheEntry<T> = {
  expiresAt: number;
  value: T;
};

const cache = new Map<string, CacheEntry<unknown>>();
const inFlight = new Map<string, Promise<unknown>>();

export async function getOrLoadCached<T>(
  key: string,
  ttlMs: number,
  loader: () => Promise<T>,
): Promise<T> {
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expiresAt > now) {
    return cached.value as T;
  }

  const running = inFlight.get(key);
  if (running) {
    return running as Promise<T>;
  }

  const next = loader()
    .then((value) => {
      cache.set(key, {
        expiresAt: Date.now() + ttlMs,
        value,
      });
      return value;
    })
    .finally(() => {
      inFlight.delete(key);
    });

  inFlight.set(key, next);
  return next;
}

export function clearMarketCache(): void {
  cache.clear();
  inFlight.clear();
}
