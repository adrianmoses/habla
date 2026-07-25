// Historial — every session, newest first.
//
// The API exposes no total count, so "cargar más" runs until a short page comes
// back (`usePagedSessions`). A session with no `ended_at` never ended cleanly —
// it is shown as in progress rather than given a fabricated duration.

import AppShell from '../components/AppShell';
import {
  Empty,
  ErrorNotice,
  Eyebrow,
  page,
  Panel,
  PageTitle,
} from '../components/ui';
import { formatDay, formatDuration, formatMode } from '../lib/format';
import { usePagedSessions } from '../lib/learner';
import type { SessionRow } from '../lib/types';

function Row({ session }: { session: SessionRow }) {
  const duration = formatDuration(session.started_at, session.ended_at);
  const mode = formatMode(session.mode);

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '90px 1fr auto',
        gap: 20,
        alignItems: 'baseline',
        padding: '18px 0',
        borderBottom: '1px solid var(--line)',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--mono)',
          fontSize: 12,
          color: 'var(--muted)',
          letterSpacing: '0.06em',
        }}
      >
        {formatDay(session.started_at)}
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span style={{ fontSize: 15, color: 'var(--ink)' }}>
          {session.theme_domain ?? 'conversación'}
        </span>
        {mode && (
          <span
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 10,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--clay-deep)',
              border: '1px solid rgba(168, 84, 58, 0.25)',
              borderRadius: 100,
              padding: '3px 9px',
            }}
          >
            {mode}
          </span>
        )}
      </div>

      <div
        style={{
          fontFamily: 'var(--mono)',
          fontSize: 12,
          color: 'var(--muted)',
          letterSpacing: '0.05em',
          whiteSpace: 'nowrap',
        }}
      >
        {session.band_at_start} · {session.turn_count}{' '}
        {session.turn_count === 1 ? 'turno' : 'turnos'} ·{' '}
        {duration ?? <span style={{ color: 'var(--clay)' }}>en curso</span>}
      </div>
    </div>
  );
}

export default function Historial() {
  const { sessions, error, loading, hasMore, loadMore } = usePagedSessions();

  const empty = !loading && !error && sessions.length === 0;

  return (
    <AppShell current="historial">
      <section style={page}>
        <PageTitle
          title="Tus conversaciones"
          subtitle={
            sessions.length > 0
              ? `${sessions.length} ${
                  sessions.length === 1 ? 'sesión' : 'sesiones'
                } hasta ahora — de la más reciente a la primera.`
              : undefined
          }
        />

        <Panel style={{ padding: '8px 24px 24px' }}>
          <div style={{ paddingTop: 16 }}>
            <Eyebrow>Sesiones</Eyebrow>
          </div>

          {error && (
            <ErrorNotice>
              No pude cargar tu historial. Vuelve a intentarlo en un momento.
            </ErrorNotice>
          )}

          {empty && (
            <Empty>
              Aún no hay conversaciones. Cuando tengas la primera, aparecerá
              aquí.
            </Empty>
          )}

          {sessions.map((s) => (
            <Row key={s.session_id} session={s} />
          ))}

          {loading && sessions.length === 0 && !error && (
            <Empty>Cargando…</Empty>
          )}

          {hasMore && sessions.length > 0 && (
            <button
              type="button"
              onClick={loadMore}
              disabled={loading}
              style={{
                marginTop: 22,
                padding: '11px 20px',
                borderRadius: 100,
                border: '1px solid var(--line)',
                background: 'transparent',
                color: 'var(--ink-2)',
                fontFamily: 'var(--sans)',
                fontSize: 13,
                cursor: loading ? 'default' : 'pointer',
              }}
            >
              {loading ? 'cargando…' : 'cargar más'}
            </button>
          )}
        </Panel>
      </section>
    </AppShell>
  );
}
