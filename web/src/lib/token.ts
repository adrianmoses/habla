// Session-auth token storage. The server (spec #016) gates `/ws/session` with a
// shared secret (`HABLE_YA_SESSION_AUTH_TOKEN`). On a publicly-served page we do
// NOT bake the token into the bundle (spec #018, Open Question 1 = Option B):
// the operator pastes it once and we keep it in `sessionStorage` — out of the
// served HTML/JS and cleared when the tab closes. `VoiceClient` reads it at
// connect time and carries it on the WebSocket subprotocol handshake.

const KEY = 'habla.sessionToken';

// sessionStorage fires no event for same-tab writes, so readers would never
// learn that a token was pasted or rejected. This is that missing signal: the
// data hooks subscribe, so saving a token starts the fetches it enables and a
// 401 stops them (spec #020).
const TOKEN_EVENT = 'habla:token';

// Guarded like the storage access below: this module is imported by pure
// logic that runs outside a DOM (unit tests today, anything non-browser
// later), and a missing `window` must not turn a token write into a crash.
function announce(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(TOKEN_EVENT));
}

export function getSessionToken(): string | undefined {
  try {
    return sessionStorage.getItem(KEY) ?? undefined;
  } catch {
    // sessionStorage can throw in private-mode / sandboxed contexts.
    return undefined;
  }
}

export function setSessionToken(token: string): void {
  try {
    sessionStorage.setItem(KEY, token.trim());
  } catch {
    // Non-fatal: if storage is unavailable the operator re-pastes next load.
  }
  announce();
}

export function clearSessionToken(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
  announce();
}

export function subscribeToken(onChange: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  window.addEventListener(TOKEN_EVENT, onChange);
  return () => window.removeEventListener(TOKEN_EVENT, onChange);
}
