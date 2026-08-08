import type { ConversationMode } from '../lib/types';

export type Speaker = 'idle' | 'user' | 'agent';

/**
 * What the learner asked for when starting a session (spec #023).
 *
 * Carried to `/ws/session` as `?mode=&topic=`. The server parses both
 * fail-safe — an unknown mode degrades to `open` and a blank topic to none —
 * so this can never break the handshake.
 */
export type SessionRequest = {
  mode: ConversationMode;
  topic?: string;
  /**
   * An opaque La Libreta handoff id (spec #033), carried as `?handoff=`.
   *
   * Only the id travels. The server re-reads the consigna, structures and
   * target from its own row after the auth gate, so the prompt the tutor is
   * given cannot be rewritten from the browser.
   */
  handoff?: string;
};
