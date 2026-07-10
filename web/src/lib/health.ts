// Readiness polling for the Home CTA. Hits the same-origin `/health` probe
// (spec #016), which returns 200 `{status:"ok"}` only when a session can
// actually run, and 503 with `status:"warming_up"` while the app warms or
// `db_unreachable`/`degraded` when something is wrong. Same-origin so it works
// in dev (Vite proxies `/health` → :8000) and in prod (Caddy routes `/health`
// → app:8000) without any base-URL config.

import { useEffect, useState } from 'react';

export type Health = 'ready' | 'warming' | 'error' | 'unknown';

const POLL_INTERVAL_MS = 4000;

async function probe(signal: AbortSignal): Promise<Health> {
  try {
    const res = await fetch('/health', { signal });
    if (res.ok) return 'ready';
    // 503 → distinguish "still coming up" (friendly wait) from a real fault.
    try {
      const body = (await res.json()) as { status?: string };
      return body.status === 'warming_up' ? 'warming' : 'error';
    } catch {
      return 'error';
    }
  } catch {
    // Aborts surface here too; the effect cleanup ignores the stale result.
    return 'error';
  }
}

export function useHealth(): Health {
  const [health, setHealth] = useState<Health>('unknown');

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const tick = async () => {
      const next = await probe(controller.signal);
      if (!cancelled) setHealth(next);
    };

    void tick();
    const id = setInterval(() => void tick(), POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(id);
    };
  }, []);

  return health;
}
