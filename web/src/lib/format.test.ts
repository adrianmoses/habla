import { describe, expect, it } from 'vitest';
import {
  computeStreak,
  dedupeTopics,
  errorLabel,
  formatDuration,
  formatMode,
  formatRelative,
  toPercent,
  vocabByProduction,
} from './format';
import type { SessionRow } from './types';

/** A local-midnight-safe ISO timestamp `daysAgo` days before `now`. */
function isoDaysAgo(daysAgo: number, now = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() - daysAgo);
  d.setHours(19, 0, 0, 0);
  return d.toISOString();
}

function session(overrides: Partial<SessionRow> = {}): SessionRow {
  return {
    session_id: `s-${Math.random()}`,
    started_at: isoDaysAgo(0),
    ended_at: null,
    theme_domain: 'pedir un café',
    band_at_start: 'A2',
    mode: 'open',
    turn_count: 3,
    ...overrides,
  };
}

describe('computeStreak', () => {
  it('is zero with no sessions', () => {
    expect(computeStreak([])).toBe(0);
  });

  it('counts consecutive days ending today', () => {
    const rows = [
      session({ started_at: isoDaysAgo(0) }),
      session({ started_at: isoDaysAgo(1) }),
      session({ started_at: isoDaysAgo(2) }),
    ];
    expect(computeStreak(rows)).toBe(3);
  });

  it('counts a same-day pair once', () => {
    const now = new Date();
    const morning = new Date(now);
    morning.setHours(9, 0, 0, 0);
    const evening = new Date(now);
    evening.setHours(21, 0, 0, 0);
    const rows = [
      session({ started_at: evening.toISOString() }),
      session({ started_at: morning.toISOString() }),
    ];
    expect(computeStreak(rows)).toBe(1);
  });

  it('stops at a gap day', () => {
    const rows = [
      session({ started_at: isoDaysAgo(0) }),
      session({ started_at: isoDaysAgo(1) }),
      // day 2 missing
      session({ started_at: isoDaysAgo(3) }),
    ];
    expect(computeStreak(rows)).toBe(2);
  });

  it('survives a day not yet practised', () => {
    // Last session was yesterday: today is still open, so the streak stands.
    const rows = [
      session({ started_at: isoDaysAgo(1) }),
      session({ started_at: isoDaysAgo(2) }),
    ];
    expect(computeStreak(rows)).toBe(2);
  });

  it('is zero after two silent days', () => {
    const rows = [session({ started_at: isoDaysAgo(2) })];
    expect(computeStreak(rows)).toBe(0);
  });

  it('ignores unparseable timestamps', () => {
    const rows = [session({ started_at: 'not-a-date' })];
    expect(computeStreak(rows)).toBe(0);
  });
});

describe('formatDuration', () => {
  it('renders whole minutes', () => {
    expect(
      formatDuration('2026-07-25T19:00:00Z', '2026-07-25T19:12:00Z'),
    ).toBe('12 min');
  });

  it('returns null when the session never ended', () => {
    // The in-progress / crashed case: end_session is what writes ended_at.
    expect(formatDuration('2026-07-25T19:00:00Z', null)).toBeNull();
  });

  it('returns null rather than a negative span', () => {
    expect(
      formatDuration('2026-07-25T19:12:00Z', '2026-07-25T19:00:00Z'),
    ).toBeNull();
  });

  it('never yields NaN for an unparseable timestamp', () => {
    expect(formatDuration('nonsense', 'also-nonsense')).toBeNull();
  });

  it('describes a sub-minute session', () => {
    expect(
      formatDuration('2026-07-25T19:00:00Z', '2026-07-25T19:00:20Z'),
    ).toBe('menos de 1 min');
  });
});

describe('formatRelative', () => {
  it('names today and yesterday', () => {
    expect(formatRelative(isoDaysAgo(0))).toBe('hoy');
    expect(formatRelative(isoDaysAgo(1))).toBe('ayer');
  });

  it('counts days inside a week', () => {
    expect(formatRelative(isoDaysAgo(3))).toBe('hace 3 días');
  });

  it('rolls up to weeks and months', () => {
    expect(formatRelative(isoDaysAgo(8))).toBe('hace una semana');
    expect(formatRelative(isoDaysAgo(20))).toBe('hace 2 semanas');
    expect(formatRelative(isoDaysAgo(45))).toBe('hace un mes');
    expect(formatRelative(isoDaysAgo(95))).toBe('hace 3 meses');
  });

  it('degrades on an unparseable timestamp', () => {
    expect(formatRelative('nope')).toBe('—');
  });
});

describe('formatMode', () => {
  it('says nothing for the unremarkable default', () => {
    expect(formatMode('open')).toBeNull();
    // Sessions predating spec #023 have no mode at all.
    expect(formatMode(null)).toBeNull();
  });

  it('labels the three steered modes', () => {
    expect(formatMode('debate')).toBe('debate');
    expect(formatMode('role_play')).toBe('juego de rol');
    expect(formatMode('interview')).toBe('entrevista');
  });

  it('still shows an unrecognised mode', () => {
    expect(formatMode('storytelling_practice')).toBe('storytelling practice');
  });
});

describe('errorLabel', () => {
  it('translates the curated eval slugs', () => {
    expect(errorLabel('ser_estar')).toBe('ser / estar');
    expect(errorLabel('gender_agreement')).toBe('concordancia de género');
  });

  it('falls back for model-authored categories', () => {
    // errors[].type has no enum in the log_turn schema, so anything can land
    // in error_counts.category — including Spanish prose Claude wrote itself.
    expect(errorLabel('concordancia de número')).toBe('concordancia de número');
    expect(errorLabel('verb tense confusion')).toBe('verb tense confusion');
    expect(errorLabel('some_new_slug')).toBe('some new slug');
  });

  it('never returns an empty label', () => {
    expect(errorLabel('   ')).toBe('   ');
  });
});

describe('dedupeTopics', () => {
  it('keeps the most recent session per topic, in order', () => {
    const rows = [
      session({ session_id: 'a', theme_domain: 'café', started_at: isoDaysAgo(0) }),
      session({ session_id: 'b', theme_domain: 'viaje', started_at: isoDaysAgo(1) }),
      session({ session_id: 'c', theme_domain: 'café', started_at: isoDaysAgo(2) }),
    ];
    const out = dedupeTopics(rows);
    expect(out.map((s) => s.session_id)).toEqual(['a', 'b']);
  });

  it('skips sessions with no topic', () => {
    const rows = [
      session({ session_id: 'a', theme_domain: null }),
      session({ session_id: 'b', theme_domain: 'viaje' }),
    ];
    expect(dedupeTopics(rows).map((s) => s.session_id)).toEqual(['b']);
  });

  it('caps at the requested limit', () => {
    const rows = Array.from({ length: 10 }, (_, i) =>
      session({ session_id: `s${i}`, theme_domain: `tema ${i}` }),
    );
    expect(dedupeTopics(rows)).toHaveLength(6);
    expect(dedupeTopics(rows, 2)).toHaveLength(2);
  });

  it('is empty for no sessions', () => {
    expect(dedupeTopics([])).toEqual([]);
  });
});

describe('vocabByProduction', () => {
  it('reorders the API recency ordering by production count', () => {
    // read.py returns top_vocab ordered by last_seen_at, so a word used twice
    // yesterday arrives ahead of one used nine times last week.
    const items = [
      { lemma: 'sueño', production_count: 2, last_seen_at: isoDaysAgo(0) },
      { lemma: 'viajar', production_count: 9, last_seen_at: isoDaysAgo(1) },
    ];
    expect(vocabByProduction(items).map((v) => v.lemma)).toEqual([
      'viajar',
      'sueño',
    ]);
  });

  it('does not mutate its input', () => {
    const items = [
      { lemma: 'a', production_count: 1, last_seen_at: isoDaysAgo(0) },
      { lemma: 'b', production_count: 5, last_seen_at: isoDaysAgo(1) },
    ];
    vocabByProduction(items);
    expect(items[0]?.lemma).toBe('a');
  });
});

describe('toPercent', () => {
  it('scales and rounds', () => {
    expect(toPercent(0.735)).toBe(74);
    expect(toPercent(0)).toBe(0);
    expect(toPercent(1)).toBe(100);
  });

  it('clamps out-of-range and non-finite values', () => {
    expect(toPercent(1.4)).toBe(100);
    expect(toPercent(-0.2)).toBe(0);
    expect(toPercent(Number.NaN)).toBe(0);
  });
});
