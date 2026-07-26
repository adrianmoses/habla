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

import { useEffect, useState } from 'react';

export type Route = 'home' | 'progreso' | 'historial' | 'ajustes';

const PATHS: Record<Route, string> = {
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

// Same-tab pushes don't fire `popstate`, so `navigate` announces them here.
const NAV_EVENT = 'habla:navigate';

export function routeFor(pathname: string): Route {
  return ROUTES[pathname] ?? 'home';
}

export function pathFor(route: Route): string {
  return PATHS[route];
}

export function navigate(route: Route): void {
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

/** Run `onPop` the next time the user goes Back. Used to exit a session. */
export function useBackHandler(active: boolean, onPop: () => void): void {
  useEffect(() => {
    if (!active) return;
    const handler = () => onPop();
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, [active, onPop]);
}
