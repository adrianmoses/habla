// Pure presentation logic for the learner-progress surfaces (spec #020).
//
// Everything here derives display values from #019's raw rows client-side —
// streaks, durations, relative times, labels. That was #019's Open Question 4
// (resolved: no server-side streak), and it keeps presentation choices out of
// the API contract. It is also the only genuinely error-prone code in #020,
// which is why it lives in one dependency-free module with unit tests.

import type { ConversationMode, SessionRow, VocabItem } from './types';

/** Local-day key. Local, not UTC: a 23:00 session belongs to that local day. */
function dayKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Whole local days between two instants, ignoring time of day. */
function daysBetween(later: Date, earlier: Date): number {
  const a = new Date(later.getFullYear(), later.getMonth(), later.getDate());
  const b = new Date(
    earlier.getFullYear(),
    earlier.getMonth(),
    earlier.getDate(),
  );
  return Math.round((a.getTime() - b.getTime()) / 86_400_000);
}

/**
 * Consecutive days with at least one session, counting back from today.
 *
 * A streak survives a day with no session *yet* — if the last session was
 * yesterday, today is still open, so the streak stands. Two days of silence
 * ends it. Multiple sessions on one day count once.
 */
export function computeStreak(
  sessions: SessionRow[],
  now: Date = new Date(),
): number {
  if (sessions.length === 0) return 0;

  const days = new Set<string>();
  for (const s of sessions) {
    const d = new Date(s.started_at);
    if (!Number.isNaN(d.getTime())) days.add(dayKey(d));
  }

  const cursor = new Date(now);
  if (!days.has(dayKey(cursor))) {
    cursor.setDate(cursor.getDate() - 1);
    if (!days.has(dayKey(cursor))) return 0;
  }

  let streak = 0;
  while (days.has(dayKey(cursor))) {
    streak += 1;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

/** "hoy" / "ayer" / "hace 3 días" / "hace 2 semanas" / "hace un mes". */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '—';

  const days = daysBetween(now, then);
  if (days <= 0) return 'hoy';
  if (days === 1) return 'ayer';
  if (days < 7) return `hace ${days} días`;
  if (days < 14) return 'hace una semana';
  if (days < 30) return `hace ${Math.floor(days / 7)} semanas`;

  const months = Math.floor(days / 30);
  return months <= 1 ? 'hace un mes' : `hace ${months} meses`;
}

/** Absolute day label for history rows: "24 jul". */
export function formatDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('es', { day: 'numeric', month: 'short' });
}

/**
 * Session length, or `null` when it cannot be known.
 *
 * `ended_at` is only written by `end_session`, so a crashed or in-flight
 * session has none — the caller renders "en curso" rather than a number. A
 * negative span (clock skew) is treated the same way, never shown as a value.
 */
export function formatDuration(
  startedAt: string,
  endedAt: string | null,
): string | null {
  if (endedAt === null) return null;
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;

  const minutes = Math.round(ms / 60_000);
  if (minutes < 1) return 'menos de 1 min';
  return `${minutes} min`;
}

export const MODE_OPTIONS: readonly { value: ConversationMode; label: string }[] =
  [
    { value: 'open', label: 'conversación libre' },
    { value: 'debate', label: 'debate' },
    { value: 'role_play', label: 'juego de rol' },
    { value: 'interview', label: 'entrevista' },
  ];

const MODE_LABELS: Record<string, string> = {
  debate: 'debate',
  role_play: 'juego de rol',
  interview: 'entrevista',
};

/**
 * Display label for a session's mode, or `null` when there is nothing to say.
 *
 * `open` and pre-#023 nulls are the unremarkable default, so they render no
 * badge. An unrecognised value still gets shown — the column is a plain TEXT
 * with a CHECK, but the UI should not silently swallow something new.
 */
export function formatMode(mode: string | null): string | null {
  if (mode === null || mode === 'open') return null;
  return MODE_LABELS[mode] ?? humanize(mode);
}

// The curated eval vocabulary (eval/agent/personas/schema.py
// ALLOWED_ERROR_PATTERNS) is the closest thing to a controlled list, but
// `errors[].type` in the log_turn tool schema has no enum — the model writes
// whatever it wants and it lands in `error_counts.category` verbatim. So this
// is a best-effort prettifier over a genuinely open vocabulary, not a lookup
// that can be exhaustive.
const ERROR_LABELS: Record<string, string> = {
  ser_estar: 'ser / estar',
  gender_agreement: 'concordancia de género',
  preterite_imperfect: 'pretérito / imperfecto',
  por_para: 'por / para',
  verb_conjugation: 'conjugación verbal',
  register_slip: 'registro (tú / usted)',
  idiomatic_error: 'expresiones idiomáticas',
  subjunctive_avoidance: 'evitar el subjuntivo',
  subjunctive: 'subjuntivo',
  missing_article: 'artículos',
  stem_changing_verbs: 'verbos con cambio de raíz',
  anglicisms: 'anglicismos',
};

function humanize(raw: string): string {
  const spaced = raw.replace(/_/g, ' ').trim().toLowerCase();
  return spaced.length > 0 ? spaced : raw;
}

export function errorLabel(category: string): string {
  return ERROR_LABELS[category] ?? humanize(category);
}

/**
 * Most recent session per distinct topic, newest first (spec OQ5).
 *
 * Relies on the API's `ORDER BY started_at DESC`; sessions with no
 * `theme_domain` are skipped since there is no topic to name.
 */
export function dedupeTopics(sessions: SessionRow[], limit = 6): SessionRow[] {
  const seen = new Set<string>();
  const out: SessionRow[] = [];
  for (const s of sessions) {
    const theme = s.theme_domain;
    if (theme === null || seen.has(theme)) continue;
    seen.add(theme);
    out.push(s);
    if (out.length === limit) break;
  }
  return out;
}

/**
 * Vocabulary ordered by how much the learner actually produces it.
 *
 * The API returns `top_vocab` ordered by `last_seen_at` (read.py), which is
 * recency, not strength — so a word used twice yesterday outranks one used
 * nine times last week. For a "what you produce comfortably" reading we sort
 * by count here rather than change the API.
 */
export function vocabByProduction(items: VocabItem[]): VocabItem[] {
  return [...items].sort((a, b) => b.production_count - a.production_count);
}

/**
 * The hero greeting, split so the name keeps its own styling (spec #021).
 *
 * Returns parts rather than one string because Home renders the name in a
 * clay-deep `<em>` on its own line — flattening it to a sentence would lose
 * the accent that makes the greeting the hero.
 *
 * With a name: `buenas tardes,` + the **first** name (the lowercase greeting is
 * the existing house style). Without one: `Buenas tardes.` alone — capitalized
 * and terminated, claiming nothing. A neutral placeholder word would just
 * reintroduce the invented identity this spec removes.
 *
 * Only the first word, because the hero is 96px serif in a `1.2fr` grid column:
 * browser verification showed a full 40-character name wrapping to **five**
 * lines and pushing the CTA below the fold. (#021's OQ3 justified the
 * 40-character bound against `maxWidth: 520`, which is on the paragraph
 * beneath the hero, not on the hero itself.) Greeting someone by their first
 * name is also simply what a person does; the full name is what Ajustes edits
 * and what the avatar initial comes from.
 */
export function greetingLine(
  time: string,
  name: string | null,
): { lead: string; name: string | null } {
  const trimmed = name?.trim() ?? '';
  if (trimmed === '') {
    const head = Array.from(time)[0] ?? '';
    return { lead: head.toUpperCase() + time.slice(head.length) + '.', name: null };
  }
  const first = trimmed.split(/\s+/)[0] ?? trimmed;
  return { lead: time + ',', name: first };
}

/**
 * The avatar letter, or an empty string when there is no name.
 *
 * `Array.from` rather than `name[0]` so a first character outside the BMP is
 * not split into half a surrogate pair. An empty return leaves a blank sand
 * circle, which still reads as an avatar and still navigates to Ajustes.
 */
export function avatarInitial(name: string | null): string {
  if (!name) return '';
  return (Array.from(name)[0] ?? '').toUpperCase();
}

/** A 0–1 model signal as a clamped whole percentage. */
export function toPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.round(Math.min(1, Math.max(0, value)) * 100);
}
