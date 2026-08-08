// Data hooks over the #019 learner-progress API.
//
// Same shape as `useHealth()`: state + useEffect + AbortController, no cache,
// no fetch library. Each hook owns its own `{data, error, loading}` so a screen
// reading two endpoints degrades one region when one fails rather than blanking
// the page (spec Key Decision: per-surface failure, not per-page).

import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { apiGet, UnauthorizedError } from './api';
import { navigate } from './router';
import { getSessionToken, subscribeToken } from './token';
import type {
  BandHistoryPage,
  LearnerProfile,
  SessionRow,
  SessionsPage,
} from './types';

export type Async<T> = {
  data: T | null;
  /** Set on failure. `UnauthorizedError` means the token was cleared. */
  error: Error | null;
  loading: boolean;
};

/**
 * The stored session token, re-rendering when it is saved or cleared.
 *
 * Without this the hooks below would fetch once on mount with whatever token
 * existed then — so pasting one on Home would populate nothing until a reload,
 * and the guaranteed 401 from a tokenless first load would race in and clear
 * the token the operator had just typed.
 */
export function useSessionToken(): string | undefined {
  return useSyncExternalStore(subscribeToken, getSessionToken, () => undefined);
}

function useApi<T>(path: string): Async<T> {
  const token = useSessionToken();
  const [state, setState] = useState<Async<T>>({
    data: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    // No token: every request would be a guaranteed 401. Stay idle and let
    // Home prompt for one rather than manufacturing an error to display.
    if (token === undefined) {
      setState({ data: null, error: null, loading: false });
      return;
    }

    setState({ data: null, error: null, loading: true });
    apiGet<T>(path, controller.signal)
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((err: unknown) => {
        // An abort is our own teardown, not a failure to report.
        if (cancelled || controller.signal.aborted) return;
        const error = err instanceof Error ? err : new Error(String(err));
        setState({ data: null, error, loading: false });
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [path, token]);

  return state;
}

export function useLearnerProfile(): Async<LearnerProfile> {
  return useApi<LearnerProfile>('/api/learner');
}

export function useBandHistory(limit = 10): Async<BandHistoryPage> {
  return useApi<BandHistoryPage>(`/api/learner/band-history?limit=${limit}`);
}

/** One page of session history — enough for Home's tiles and topic cards. */
export function useSessions(limit = 20): Async<SessionsPage> {
  return useApi<SessionsPage>(`/api/learner/sessions?limit=${limit}`);
}

export type PagedSessions = {
  sessions: SessionRow[];
  error: Error | null;
  loading: boolean;
  /** False once a short page comes back — the API exposes no total count. */
  hasMore: boolean;
  loadMore: () => void;
};

/**
 * Accumulating session history for Historial's "cargar más".
 *
 * `/api/learner/sessions` returns no total, so the end of the list is a page
 * shorter than `pageSize` (or an empty one). `limit` is capped at 100 server
 * side; the default page is well under that.
 */
export function usePagedSessions(pageSize = 20): PagedSessions {
  const token = useSessionToken();
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    if (token === undefined) {
      setLoading(false);
      setHasMore(false);
      return;
    }

    setLoading(true);
    apiGet<SessionsPage>(
      `/api/learner/sessions?limit=${pageSize}&offset=${offset}`,
      controller.signal,
    )
      .then((page) => {
        if (cancelled) return;
        setSessions((prev) =>
          offset === 0 ? page.sessions : [...prev, ...page.sessions],
        );
        setHasMore(page.sessions.length === pageSize);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [offset, pageSize, token]);

  const loadMore = useCallback(() => {
    setOffset((prev) => prev + pageSize);
  }, [pageSize]);

  return { sessions, error, loading, hasMore, loadMore };
}

/** True when a failure was an auth rejection — the caller should re-prompt. */
export function isAuthError(error: Error | null): boolean {
  return error instanceof UnauthorizedError;
}

/**
 * Keep the token-less user on Home, where the paste prompt lives.
 *
 * Stated as a rule about the token rather than about errors, deliberately. A
 * 401 clears the token inside `apiGet`, which re-runs every hook with no token
 * — wiping the very error a per-screen "did this fail with 401?" check would
 * have needed to observe, and stranding the user on an empty screen with no
 * explanation. Watching the token instead covers that, a deep link with no
 * token, and a manual clear from Ajustes, with one rule.
 */
export function useAuthGuard(route: string): void {
  const token = useSessionToken();
  // `handoff` is exempt (spec #033). A La Libreta deep link must survive the
  // auth round trip: bouncing a tokenless visitor to Home would lose the id
  // they arrived with, so that screen asks for the token in place and resumes
  // the same pre-session view once it is saved.
  const stranded =
    token === undefined && route !== 'home' && route !== 'handoff';
  useEffect(() => {
    if (stranded) navigate('home');
  }, [stranded]);
}
