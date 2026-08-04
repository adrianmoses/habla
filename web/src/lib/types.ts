// TypeScript mirrors of the #019 learner-progress read API payloads.
//
// Transcribed field-by-field from `hable_ya/learner/read.py` (profile_payload /
// session_history / band_history) and checked against live responses from a
// seeded database. Timestamps are ISO-8601 strings; JSONB arrives decoded.
//
// If a field here stops matching the API, the API is right and this is stale —
// #020 adds no backend surface.

export type CEFRBand = 'A1' | 'A2' | 'B1' | 'B2' | 'C1';

export type ConversationMode = 'open' | 'debate' | 'role_play' | 'interview';

export type BandChangeReason =
  | 'placement'
  | 'auto_promote'
  | 'auto_demote'
  | 'manual';

export type ErrorCount = {
  // Free-form. `errors[].type` in the log_turn schema is an unconstrained
  // string (hable_ya/tools/schema.py) — the model writes the category, so this
  // holds anything from `ser_estar` to `concordancia de número`. Render it
  // through `errorLabel()`, never assume a closed vocabulary.
  category: string;
  count: number;
  last_seen_at: string;
};

export type VocabItem = {
  lemma: string;
  production_count: number;
  // NOTE: the API orders `top_vocab` by this, not by production_count.
  last_seen_at: string;
};

export type LearnerProfile = {
  band: CEFRBand;
  // Null until the learner sets one in Ajustes (spec #021). Null means "not
  // set" and must render as nothing — never a placeholder name.
  display_name: string | null;
  sessions_completed: number;
  l1_reliance: number;
  speech_fluency: number;
  error_patterns: string[];
  vocab_strengths: string[];
  is_calibrated: boolean;
  stable_sessions_at_band: number;
  last_band_change_at: string | null;
  top_errors: ErrorCount[];
  top_vocab: VocabItem[];
  recent_theme_domains: string[];
};

export type SessionRow = {
  session_id: string;
  started_at: string;
  // Only `end_session` sets this, so a crashed or in-flight session leaves it
  // null. Every duration calculation must handle that.
  ended_at: string | null;
  theme_domain: string | null;
  band_at_start: CEFRBand;
  // Null on sessions predating spec #023.
  mode: ConversationMode | null;
  turn_count: number;
};

export type SessionsPage = {
  sessions: SessionRow[];
  limit: number;
  offset: number;
};

export type BandChange = {
  id: number;
  from_band: CEFRBand | null;
  to_band: CEFRBand;
  reason: BandChangeReason;
  signals: Record<string, unknown>;
  changed_at: string;
};

export type BandHistoryPage = {
  band_history: BandChange[];
};
