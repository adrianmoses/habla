import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet, UnauthorizedError } from './api';
import { clearSessionToken, getSessionToken, setSessionToken } from './token';

// `lib/token.ts` talks to sessionStorage, which the node test environment has
// no implementation of. A tiny in-memory stand-in keeps the module under test
// honest (it exercises the real get/set/clear) without pulling in jsdom.
class MemoryStorage {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  vi.stubGlobal('sessionStorage', new MemoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('apiGet', () => {
  it('attaches the stored token as a Bearer header', async () => {
    setSessionToken('s3cret');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ band: 'B1' }));
    vi.stubGlobal('fetch', fetchMock);

    const data = await apiGet<{ band: string }>('/api/learner');

    expect(data).toEqual({ band: 'B1' });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.headers).toEqual({ Authorization: 'Bearer s3cret' });
  });

  it('sends no auth header when no token is stored', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    await apiGet('/api/learner');

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.headers).toBeUndefined();
  });

  it('clears the token and throws on 401', async () => {
    setSessionToken('stale');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({}, 401)));

    await expect(apiGet('/api/learner')).rejects.toBeInstanceOf(
      UnauthorizedError,
    );
    // Cleared, so Home re-prompts instead of retrying a dead secret forever.
    expect(getSessionToken()).toBeUndefined();
  });

  it('surfaces other failures with their status', async () => {
    setSessionToken('ok');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({}, 503)));

    const err = await apiGet('/api/learner').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(503);
    // A 503 is the server warming, not a bad token — keep it.
    expect(getSessionToken()).toBe('ok');
  });

  it('propagates an abort without clearing the token', async () => {
    setSessionToken('ok');
    const abort = new DOMException('aborted', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abort));

    await expect(apiGet('/api/learner')).rejects.toBe(abort);
    expect(getSessionToken()).toBe('ok');
  });

  it('passes the abort signal through to fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();

    await apiGet('/api/learner', controller.signal);

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
  });

  it('trims a pasted token before storing it', async () => {
    setSessionToken('  padded  ');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal('fetch', fetchMock);

    await apiGet('/api/learner');

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.headers).toEqual({ Authorization: 'Bearer padded' });
    clearSessionToken();
  });
});
