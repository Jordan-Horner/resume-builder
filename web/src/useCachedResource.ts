import { useCallback, useEffect, useRef, useState } from "react";

const cache = new Map<string, unknown>();

/** Test-only: forget every cached resource so each test starts from a clean slate. */
export function __resetCachedResources(): void {
  cache.clear();
}

/**
 * Fetch-once-per-session, stale-while-revalidate resource.
 *
 * The portal's pages and settings sections fully unmount on navigation, so a
 * plain `useEffect` fetch re-shows a full loading placeholder and repeats an
 * unchanged network call on every revisit. Seeding state from a module-level
 * cache lets a revisit render its last-known content immediately while a
 * background refetch keeps it current; a failed background refetch is
 * swallowed rather than replacing good content with an error.
 */
export function useCachedResource<T>(key: string, fetcher: () => Promise<T>) {
  const [data, setDataState] = useState<T | null>(() => (cache.has(key) ? (cache.get(key) as T) : null));
  const [error, setError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let active = true;
    const hadCachedValue = cache.has(key);
    setError("");
    fetcherRef.current().then((value) => {
      if (!active) return;
      cache.set(key, value);
      setDataState(value);
    }).catch((reason: unknown) => {
      if (!active || hadCachedValue) return;
      setError(reason instanceof Error ? reason.message : "Could not load this page.");
    });
    return () => { active = false; };
  }, [key, reloadToken]);

  const reload = useCallback(() => setReloadToken((value) => value + 1), []);
  const setData = useCallback((value: T) => { cache.set(key, value); setDataState(value); }, [key]);

  return { data, loading: data === null && !error, error, reload, setData };
}
