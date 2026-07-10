// Session-auth token storage. The server (spec #016) gates `/ws/session` with a
// shared secret (`HABLE_YA_SESSION_AUTH_TOKEN`). On a publicly-served page we do
// NOT bake the token into the bundle (spec #018, Open Question 1 = Option B):
// the operator pastes it once and we keep it in `sessionStorage` — out of the
// served HTML/JS and cleared when the tab closes. `VoiceClient` reads it at
// connect time and carries it on the WebSocket subprotocol handshake.

const KEY = 'habla.sessionToken';

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
}

export function clearSessionToken(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
