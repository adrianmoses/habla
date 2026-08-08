// Minimal history-API router (spec #020, Open Question 1).
//
// Five flat routes, no params, no nesting — so `react-router-dom` would be a
// dependency and a bundle cost for something this file does in forty lines.
// Deep links already work at the edge: the prod Caddyfile serves
// `try_files {path} /index.html` and the Vite dev server does the same.
//
// The live voice session is deliberately NOT a route (Open Question 2). It
// holds a microphone permission and an open paid-API socket; restoring it from
// a bookmark or a reload would silently reopen both. It stays in-app state on
// `/`, and `pushSessionEntry` gives the browser Back button something to pop so
// leaving a session runs a clean disconnect.
//
// `/session/:id` (spec #033) is the one parameterized route, and it does not
// contradict that: it addresses a *handoff* — a durable row La Libreta created
// — not a live session. Landing on it renders a pre-session view and starts
// nothing; the live session it can lead to remains in-app state. One extra
// prefix match is still cheaper than taking on `react-router-dom` for it.

import { useEffect, useState } from 'react';

/** `handoff` is path-parameterized and so has no entry in `PATHS`. */
export type Route = 'home' | 'progreso' | 'historial' | 'ajustes' | 'handoff';

/** The flat, navigable routes — the ones `navigate()` can be given. */
export type NavRoute = Exclude<Route, 'handoff'>;

const PATHS: Record<NavRoute, string> = {
  home: '/',
  progreso: '/progreso',
  historial: '/historial',
  ajustes: '/ajustes',
};

const ROUTES: Record<string, Route> = {
  '/': 'home',
  '/progreso': 'progreso',
  '/historial': 'historial',
  '/ajustes': 'ajustes',
};

const HANDOFF_PREFIX = '/session/';

// Opaque server-minted ids (`sess_` + hex). Matched by shape rather than by
// exact format so the id stays the server's business, but constrained enough
// that a path like `/session/../admin` can never become a request path.
const HANDOFF_ID = /^[A-Za-z0-9_-]{1,128}$/;

// Same-tab pushes don't fire `popstate`, so `navigate` announces them here.
const NAV_EVENT = 'habla:navigate';

/**
 * The handoff id in `/session/:id`, or null when this isn't that route.
 *
 * A malformed or empty id yields null, which `routeFor` reads as Home — the
 * not-found state below is for ids that are *well-formed but unknown to the
 * server*, which is the only case worth an explanation.
 */
export function handoffIdFor(pathname: string): string | null {
  if (!pathname.startsWith(HANDOFF_PREFIX)) return null;
  const rest = pathname.slice(HANDOFF_PREFIX.length).replace(/\/+$/, '');
  return HANDOFF_ID.test(rest) ? rest : null;
}

export function routeFor(pathname: string): Route {
  if (handoffIdFor(pathname) !== null) return 'handoff';
  return ROUTES[pathname] ?? 'home';
}

export function pathFor(route: NavRoute): string {
  return PATHS[route];
}

export function navigate(route: NavRoute): void {
  const path = pathFor(route);
  if (window.location.pathname !== path) {
    window.history.pushState({}, '', path);
  }
  window.dispatchEvent(new Event(NAV_EVENT));
}

/**
 * Push a history entry for a starting session so Back exits it.
 *
 * The URL does not change — this only gives `popstate` something to fire on,
 * which `Session` translates into a clean disconnect.
 */
export function pushSessionEntry(): void {
  window.history.pushState({ session: true }, '', window.location.pathname);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() =>
    routeFor(window.location.pathname),
  );

  useEffect(() => {
    const sync = () => setRoute(routeFor(window.location.pathname));
    window.addEventListener('popstate', sync);
    window.addEventListener(NAV_EVENT, sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener(NAV_EVENT, sync);
    };
  }, []);

  return route;
}

/** The current `/session/:id` id, tracking navigation the same way. */
export function useHandoffId(): string | null {
  const [id, setId] = useState<string | null>(() =>
    handoffIdFor(window.location.pathname),
  );

  useEffect(() => {
    const sync = () => setId(handoffIdFor(window.location.pathname));
    window.addEventListener('popstate', sync);
    window.addEventListener(NAV_EVENT, sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener(NAV_EVENT, sync);
    };
  }, []);

  return id;
}

/** Run `onPop` the next time the user goes Back. Used to exit a session. */
export function useBackHandler(active: boolean, onPop: () => void): void {
  useEffect(() => {
    if (!active) return;
    const handler = () => onPop();
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, [active, onPop]);
}
