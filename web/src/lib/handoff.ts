// La Libreta deep-link resolution (spec #033).
//
// `/session/:id` is the one route a person can arrive at cold — from another
// app, a bookmark, or a reload — so it is the one route that has to answer for
// every state it can be in *before* anything starts. That is what this module
// is: the state machine behind the pre-session view, kept out of the component
// so each transition is testable without a DOM.
//
// The load-bearing rule is that resolving is read-only. Reaching this screen
// fetches one JSON document and nothing else — no microphone, no WebSocket, no
// paid API call — and every one of those only ever happens from an explicit
// press on the start button (spec Key Decision 5).

import { useCallback, useEffect, useState } from 'react';
import { ApiError, apiGet, apiPost, UnauthorizedError } from './api';
import { useSessionToken } from './learner';
import type { SessionRequest } from '../voice/types';

/** The server's view of a handoff — `GET /api/sessions/:id`. */
export type Handoff = {
  id: string;
  source: string;
  sourceRef: string;
  mode: string;
  text: string;
  structures: string[];
  target: string;
  date: string;
  createdAt: string;
  completedAt: string | null;
};

export type HandoffState =
  | { status: 'loading' }
  /** No session token yet. The route is held, not abandoned. */
  | { status: 'needs-token' }
  | { status: 'ready'; handoff: Handoff }
  /** Well-formed id the server doesn't know. Explicitly not a fallback to Home. */
  | { status: 'not-found' }
  | { status: 'error' };

/**
 * Map a failed resolution onto a state.
 *
 * A 401 is `needs-token`, not `error`: `apiGet` has already cleared the stale
 * secret, so the honest next step is the same paste prompt a first visit gets,
 * on the same URL.
 */
export function stateForError(error: unknown): HandoffState {
  if (error instanceof UnauthorizedError) return { status: 'needs-token' };
  if (error instanceof ApiError && error.status === 404) {
    return { status: 'not-found' };
  }
  return { status: 'error' };
}

/**
 * What the pre-session view puts on screen.
 *
 * An identity mapping, on purpose and asserted by a test: `text`, `structures`
 * and `target` are La Libreta's words, and the spec says they are rendered
 * verbatim. Nothing here truncates, title-cases, sentence-splits, or reflows
 * them, so a future "small tidy-up" has to walk past a test that says not to.
 */
export function renderableFields(handoff: Handoff): {
  text: string;
  structures: string[];
  target: string;
} {
  return {
    text: handoff.text,
    structures: handoff.structures,
    target: handoff.target,
  };
}

/**
 * The session to start from a handoff — the opaque id and nothing else.
 *
 * The prompt, structures and target stay on the server. The browser holds a
 * rendered copy for the learner to read, but it is not authoritative and is
 * never sent back, so editing it (or the URL) cannot change what the tutor is
 * actually told.
 */
export function startRequestFor(handoff: Handoff): SessionRequest {
  return { mode: 'open', handoff: handoff.id };
}

/**
 * Resolve `/session/:id`, re-running when a token is pasted.
 *
 * The token dependency is what makes auth recovery work without navigation:
 * saving one on this screen re-runs the fetch and the view becomes `ready` in
 * place.
 */
export function useHandoff(id: string | null): HandoffState {
  const token = useSessionToken();
  const [state, setState] = useState<HandoffState>({ status: 'loading' });

  useEffect(() => {
    if (id === null) {
      setState({ status: 'not-found' });
      return;
    }
    if (token === undefined) {
      setState({ status: 'needs-token' });
      return;
    }

    let cancelled = false;
    const controller = new AbortController();
    setState({ status: 'loading' });

    apiGet<Handoff>(`/api/sessions/${id}`, controller.signal)
      .then((handoff) => {
        if (!cancelled) setState({ status: 'ready', handoff });
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setState(stateForError(error));
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [id, token]);

  return state;
}

export type CompletionState = 'idle' | 'sending' | 'done' | 'failed';

/**
 * The explicit completion action (spec Open Question 1).
 *
 * Separate from leaving the session, which is what makes it meaningful:
 * closing the tab, losing the connection, or being preempted all end a session
 * without the learner having finished the task, and only this call tells La
 * Libreta that practice happened.
 *
 * Repeat presses are harmless — the server transitions once — but the local
 * `done` latch stops the second request from being made at all.
 */
export function useCompleteHandoff(id: string | undefined): {
  state: CompletionState;
  complete: () => Promise<void>;
} {
  const [state, setState] = useState<CompletionState>('idle');

  const complete = useCallback(async () => {
    if (id === undefined || state === 'sending' || state === 'done') return;
    setState('sending');
    try {
      await apiPost<Handoff>(`/api/sessions/${id}/complete`);
      setState('done');
    } catch {
      // Never blocks the learner: completion failing is worth showing, but the
      // session still ends and the local practice still happened.
      setState('failed');
    }
  }, [id, state]);

  return { state, complete };
}
