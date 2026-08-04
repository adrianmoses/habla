// Client for the #019 learner-progress API — read, plus #021's one write.
//
// Same-origin `fetch` with no base URL — exactly as `lib/health.ts` hits
// `/health` — so it works in dev (Vite proxies `/api` → :8000) and in prod
// (Caddy routes `/api/*` → app:8000) with no configuration. The #016 shared
// secret travels as `Authorization: Bearer`, never in the URL.
//
// A 401 means the stored token is wrong or was rotated. We clear it here so the
// app falls back to Home's paste prompt — the same recovery `Session.tsx` runs
// when the WebSocket closes with 1008.

import { clearSessionToken, getSessionToken } from './token';

/** The stored token was missing, wrong, or rotated. Token already cleared. */
export class UnauthorizedError extends Error {
  constructor() {
    super('unauthorized');
    this.name = 'UnauthorizedError';
  }
}

/** Any other non-2xx response. `status` distinguishes 503 from 500. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`api error ${status}`);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const token = getSessionToken();
  const res = await fetch(path, {
    signal,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });

  if (res.status === 401) {
    clearSessionToken();
    throw new UnauthorizedError();
  }
  if (!res.ok) throw new ApiError(res.status);

  return (await res.json()) as T;
}

/**
 * PATCH with a JSON body — the write half of the API (spec #021).
 *
 * Same auth header and the same 401 recovery as `apiGet`, deliberately: a
 * rotated token has to drop the operator back to the paste prompt identically
 * whether they were reading or writing.
 */
export async function apiPatch<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const token = getSessionToken();
  const res = await fetch(path, {
    method: 'PATCH',
    signal,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });

  if (res.status === 401) {
    clearSessionToken();
    throw new UnauthorizedError();
  }
  if (!res.ok) throw new ApiError(res.status);

  return (await res.json()) as T;
}
