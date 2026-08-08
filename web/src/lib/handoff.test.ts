import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiGet, apiPost, ApiError, UnauthorizedError } from './api';
import {
  type Handoff,
  renderableFields,
  startRequestFor,
  stateForError,
} from './handoff';
import { handoffIdFor, routeFor } from './router';
import { getSessionToken, setSessionToken } from './token';

// Same stand-in as `api.test.ts`: `lib/token.ts` talks to sessionStorage, which
// the node test environment has no implementation of.
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

// Deliberately awkward strings: accents, an em dash, markdown-ish characters,
// and a newline. If anything on the path normalizes, one of these moves.
const HANDOFF: Handoff = {
  id: 'sess_2x9c',
  source: 'la-libreta',
  sourceRef: 'p02',
  mode: 'speaking',
  text: 'Describe una decisión que habrías tomado de otra forma\n— ## si hubieras sabido entonces lo que sabes ahora.',
  structures: ['condicional compuesto', 'pluscuamperfecto de subjuntivo'],
  target: 'monólogo de 3 minutos',
  date: '2026-05-02',
  createdAt: '2026-05-02T07:14:22Z',
  completedAt: null,
};

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

describe('deep-link routing', () => {
  it('resolves /session/:id from a cold direct navigation', () => {
    expect(handoffIdFor('/session/sess_2x9c')).toBe('sess_2x9c');
    expect(routeFor('/session/sess_2x9c')).toBe('handoff');
  });

  it('resolves the same id on a reload, with or without a trailing slash', () => {
    // A reload re-enters through `window.location.pathname` with no in-app
    // state, so parsing has to be a pure function of the path — this is that
    // property, not a re-test of the line above.
    expect(handoffIdFor('/session/sess_2x9c/')).toBe('sess_2x9c');
  });

  it('is not a handoff route without a well-formed id', () => {
    for (const path of [
      '/session',
      '/session/',
      '/session/a/b',
      '/session/../ajustes',
      '/session/id%2Fwith%2Fslash',
    ]) {
      expect(handoffIdFor(path)).toBeNull();
      expect(routeFor(path)).toBe('home');
    }
  });

  it('leaves the flat routes alone', () => {
    expect(routeFor('/')).toBe('home');
    expect(routeFor('/progreso')).toBe('progreso');
    expect(routeFor('/desconocido')).toBe('home');
  });
});

describe('resolving a handoff', () => {
  it('renders the contract fields verbatim', async () => {
    setSessionToken('learner-secret');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(HANDOFF)));

    const resolved = await apiGet<Handoff>('/api/sessions/sess_2x9c');
    const fields = renderableFields(resolved);

    expect(fields.text).toBe(HANDOFF.text);
    expect(fields.structures).toEqual(HANDOFF.structures);
    expect(fields.target).toBe(HANDOFF.target);
  });

  it('reads the handoff and does nothing else', async () => {
    // The safety property of the pre-session view: arriving at the deep link
    // costs exactly one read. No POST, no completion, no start.
    setSessionToken('learner-secret');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(HANDOFF));
    vi.stubGlobal('fetch', fetchMock);

    await apiGet<Handoff>('/api/sessions/sess_2x9c');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBeUndefined(); // fetch default: GET
  });

  it('reports an unknown id as not-found rather than falling back Home', async () => {
    setSessionToken('learner-secret');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({}, 404)));

    const error = await apiGet('/api/sessions/sess_gone').catch(
      (err: unknown) => err,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(stateForError(error)).toEqual({ status: 'not-found' });
  });

  it('turns a rejected token into the paste prompt, not an error screen', async () => {
    setSessionToken('rotated');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({}, 401)));

    const error = await apiGet('/api/sessions/sess_2x9c').catch(
      (err: unknown) => err,
    );

    expect(error).toBeInstanceOf(UnauthorizedError);
    // `apiGet` drops the stale secret, and the deep link asks for a new one in
    // place — the route is never abandoned, so the id survives the round trip.
    expect(getSessionToken()).toBeUndefined();
    expect(stateForError(error)).toEqual({ status: 'needs-token' });
  });

  it('treats any other failure as a retryable error', () => {
    expect(stateForError(new ApiError(503))).toEqual({ status: 'error' });
    expect(stateForError(new Error('boom'))).toEqual({ status: 'error' });
  });
});

describe('starting from a handoff', () => {
  it('sends the opaque id and none of the prompt', () => {
    const request = startRequestFor(HANDOFF);

    expect(request).toEqual({ mode: 'open', handoff: 'sess_2x9c' });
    // The browser holds a rendered copy for the learner to read; it is not
    // authoritative and must not travel back, or editing it would change what
    // the tutor is told.
    expect(JSON.stringify(request)).not.toContain('decisión');
    expect(JSON.stringify(request)).not.toContain('condicional');
  });
});

describe('completing a handoff', () => {
  it('posts to the completion route with the learner token', async () => {
    setSessionToken('learner-secret');
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ ...HANDOFF, completedAt: 'now' }));
    vi.stubGlobal('fetch', fetchMock);

    await apiPost('/api/sessions/sess_2x9c/complete');

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe('/api/sessions/sess_2x9c/complete');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({ Authorization: 'Bearer learner-secret' });
    // No body: the server owns every field, so there is nothing to tamper with.
    expect(init.body).toBeUndefined();
  });
});
