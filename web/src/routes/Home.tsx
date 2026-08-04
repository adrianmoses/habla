import type { CSSProperties } from 'react';
import { useState } from 'react';
import AgentCard from '../components/AgentCard';
import AppShell from '../components/AppShell';
import OrbHalo from '../components/orb/OrbHalo';
import { ArrowRightIcon, MicIcon } from '../components/icons';
import { Empty, ErrorNotice } from '../components/ui';
import { useHealth } from '../lib/health';
import {
  computeStreak,
  dedupeTopics,
  formatDuration,
  formatMode,
  formatRelative,
  greetingLine,
  MODE_OPTIONS,
} from '../lib/format';
import {
  isAuthError,
  useLearnerProfile,
  useSessions,
  useSessionToken,
} from '../lib/learner';
import { navigate } from '../lib/router';
import { setSessionToken } from '../lib/token';
import type { ConversationMode } from '../lib/types';
import type { SessionRequest } from '../voice/types';

type Props = {
  onStart: (request: SessionRequest) => void;
  error?: string;
};

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'buenos días';
  if (h < 19) return 'buenas tardes';
  return 'buenas noches';
}

const tileValue = (serif: boolean): CSSProperties => ({
  fontFamily: serif ? 'var(--serif)' : 'var(--sans)',
  fontSize: serif ? 36 : 22,
  fontWeight: serif ? 400 : 500,
  marginTop: 6,
  color: 'var(--ink)',
  letterSpacing: '-0.01em',
});

export default function Home({ onStart, error }: Props) {
  const [hover, setHover] = useState(false);
  const [time] = useState(greeting);
  const health = useHealth();

  const profile = useLearnerProfile();
  const sessions = useSessions();

  const [mode, setMode] = useState<ConversationMode>('open');
  const [topic, setTopic] = useState('');

  // Session-auth token (spec #018, OQ1 Option B): pasted once by the operator,
  // kept in sessionStorage — never baked into the bundle. Read reactively, so
  // saving one immediately starts the learner fetches and a 401 (which clears
  // it in `apiGet`) drops straight back to this prompt.
  const [tokenDraft, setTokenDraft] = useState('');
  const hasToken = useSessionToken() !== undefined;

  const saveToken = () => {
    const t = tokenDraft.trim();
    if (!t) return;
    setSessionToken(t);
    setTokenDraft('');
  };

  const ready = health === 'ready';
  const warming = health === 'warming' || health === 'unknown';

  const ctaLabel = ready
    ? 'Empezar a hablar'
    : warming
      ? 'María está despertando…'
      : 'Servidor no disponible';
  const ctaHelper = ready
    ? 'MICRÓFONO SE ACTIVA · 10–15 MIN'
    : warming
      ? 'ESPERANDO AL SERVIDOR…'
      : 'REVISA LA CONEXIÓN';

  const rows = sessions.data?.sessions ?? [];
  const latest = rows[0];
  const streak = computeStreak(rows);
  const topics = dedupeTopics(rows);
  const p = profile.data;
  const hello = greetingLine(time, p?.display_name ?? null);

  const start = (override?: string) => {
    const chosen = (override ?? topic).trim();
    onStart({ mode, ...(chosen ? { topic: chosen } : {}) });
  };

  return (
    <AppShell current="home">
      <section
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '1.2fr 1fr',
          gap: 80,
          padding: '40px 80px 80px',
          alignItems: 'center',
        }}
      >
        <div>
          <div
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 11,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: 'var(--muted)',
              marginBottom: 24,
            }}
          >
            <span style={{ color: 'var(--clay)' }}>●</span> &nbsp; LISTO PARA
            ESCUCHAR
          </div>
          <h1
            style={{
              fontFamily: 'var(--serif)',
              fontWeight: 400,
              fontSize: 96,
              lineHeight: 1.02,
              letterSpacing: '-0.025em',
              color: 'var(--ink)',
              marginBottom: 20,
            }}
          >
            {hello.lead}
            {hello.name !== null && (
              <>
                <br />
                <em style={{ color: 'var(--clay-deep)' }}>{hello.name}</em>.
              </>
            )}
          </h1>
          <p
            style={{
              fontFamily: 'var(--serif)',
              fontSize: 24,
              lineHeight: 1.4,
              color: 'var(--ink-2)',
              maxWidth: 520,
              marginBottom: error ? 20 : 40,
            }}
          >
            Cuando presiones hablar, yo te escucho. Sin botones para pensar,
            solo conversación — en el ritmo que tú necesites.
          </p>

          {error && (
            <div style={{ marginBottom: 28, maxWidth: 520 }}>
              <ErrorNotice>{error}</ErrorNotice>
            </div>
          )}

          {!hasToken ? (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                maxWidth: 520,
              }}
            >
              <label
                style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  color: 'var(--muted)',
                }}
              >
                Token de acceso
              </label>
              <div style={{ display: 'flex', gap: 10 }}>
                <input
                  type="password"
                  value={tokenDraft}
                  onChange={(e) => setTokenDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveToken();
                  }}
                  placeholder="Pega el token del servidor…"
                  autoComplete="off"
                  style={{
                    flex: 1,
                    padding: '14px 16px',
                    borderRadius: 12,
                    border: '1px solid var(--line)',
                    background: 'var(--cream-2)',
                    color: 'var(--ink)',
                    fontFamily: 'var(--mono)',
                    fontSize: 13,
                    outline: 'none',
                  }}
                />
                <button
                  type="button"
                  onClick={saveToken}
                  disabled={!tokenDraft.trim()}
                  style={{
                    padding: '14px 22px',
                    borderRadius: 12,
                    border: 'none',
                    background: tokenDraft.trim()
                      ? 'var(--ink)'
                      : 'var(--muted)',
                    color: 'var(--cream)',
                    fontFamily: 'var(--sans)',
                    fontSize: 14,
                    fontWeight: 500,
                    cursor: tokenDraft.trim() ? 'pointer' : 'not-allowed',
                  }}
                >
                  Guardar
                </button>
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--muted)',
                  fontFamily: 'var(--mono)',
                  letterSpacing: '0.04em',
                }}
              >
                Se guarda solo en esta pestaña · no se envía a ningún tercero.
              </div>
            </div>
          ) : (
            <>
              {/* Conversation mode (spec #023). Fixed at session start — the
                  server takes it as a query param and never mid-session. */}
              <div style={{ marginBottom: 22, maxWidth: 520 }}>
                <div
                  style={{
                    fontFamily: 'var(--mono)',
                    fontSize: 10,
                    letterSpacing: '0.18em',
                    textTransform: 'uppercase',
                    color: 'var(--muted)',
                    marginBottom: 10,
                  }}
                >
                  ¿Cómo quieres practicar?
                </div>
                <div
                  style={{
                    display: 'flex',
                    gap: 8,
                    flexWrap: 'wrap',
                    marginBottom: 10,
                  }}
                >
                  {MODE_OPTIONS.map((opt) => {
                    const active = mode === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setMode(opt.value)}
                        style={{
                          padding: '8px 14px',
                          borderRadius: 100,
                          border: active
                            ? '1px solid var(--clay)'
                            : '1px solid var(--line)',
                          background: active
                            ? 'rgba(200, 116, 84, 0.1)'
                            : 'transparent',
                          color: active ? 'var(--clay-deep)' : 'var(--ink-2)',
                          fontFamily: 'var(--sans)',
                          fontSize: 13,
                          cursor: 'pointer',
                          transition: 'all 0.15s',
                        }}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
                <input
                  type="text"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="¿Sobre qué? (opcional)"
                  style={{
                    width: '100%',
                    padding: '11px 15px',
                    borderRadius: 12,
                    border: '1px solid var(--line)',
                    background: 'var(--cream-2)',
                    color: 'var(--ink)',
                    fontFamily: 'var(--sans)',
                    fontSize: 13,
                    outline: 'none',
                  }}
                />
              </div>

              <button
                type="button"
                disabled={!ready}
                onMouseEnter={() => setHover(true)}
                onMouseLeave={() => setHover(false)}
                onClick={() => start()}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 18,
                  padding: '22px 28px 22px 22px',
                  borderRadius: 100,
                  background: ready ? 'var(--ink)' : 'var(--muted)',
                  color: 'var(--cream)',
                  border: 'none',
                  cursor: ready ? 'pointer' : 'not-allowed',
                  opacity: ready ? 1 : 0.75,
                  fontFamily: 'var(--sans)',
                  fontSize: 15,
                  letterSpacing: '0.01em',
                  boxShadow:
                    ready && hover
                      ? '0 20px 50px rgba(168, 84, 58, 0.35)'
                      : '0 10px 30px rgba(42, 33, 26, 0.18)',
                  transform:
                    ready && hover ? 'translateY(-2px)' : 'translateY(0)',
                  transition: 'all 0.25s cubic-bezier(.4,0,.2,1)',
                }}
              >
                <span
                  style={{
                    width: 46,
                    height: 46,
                    borderRadius: '50%',
                    background: 'var(--clay)',
                    display: 'grid',
                    placeItems: 'center',
                    transition: 'background 0.2s',
                  }}
                >
                  <MicIcon size={20} stroke="var(--cream)" />
                </span>
                <span
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                  }}
                >
                  <span style={{ fontSize: 16, fontWeight: 500 }}>
                    {ctaLabel}
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      opacity: 0.6,
                      fontFamily: 'var(--mono)',
                      letterSpacing: '0.1em',
                    }}
                  >
                    {ctaHelper}
                  </span>
                </span>
                <ArrowRightIcon
                  size={18}
                  stroke="var(--cream)"
                  style={{ marginLeft: 24, opacity: 0.8 }}
                />
              </button>
            </>
          )}

          <div
            style={{
              marginTop: 20,
              fontSize: 12,
              color: 'var(--muted)',
              fontFamily: 'var(--mono)',
              letterSpacing: '0.05em',
            }}
          >
            No te preocupes por el nivel — yo me adapto.
          </div>
        </div>

        <div style={{ position: 'relative', padding: 32 }}>
          <div
            style={{
              position: 'relative',
              height: 360,
              display: 'grid',
              placeItems: 'center',
              marginBottom: 32,
            }}
          >
            <OrbHalo speaker="idle" amp={0.5} size={340} />
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              gap: 1,
              background: 'var(--line)',
              border: '1px solid var(--line)',
              borderRadius: 14,
              overflow: 'hidden',
            }}
          >
            <div style={{ padding: '20px 22px', background: 'var(--cream)' }}>
              <div
                style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 10,
                  letterSpacing: '0.18em',
                  color: 'var(--muted)',
                }}
              >
                RACHA
              </div>
              <div style={tileValue(true)}>
                {streak > 0 ? streak : '—'}{' '}
                <span
                  style={{
                    fontSize: 14,
                    color: 'var(--muted)',
                    fontFamily: 'var(--sans)',
                    fontWeight: 400,
                  }}
                >
                  {streak === 1 ? 'día' : 'días'}
                </span>
              </div>
            </div>

            <div style={{ padding: '20px 22px', background: 'var(--cream)' }}>
              <div
                style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 10,
                  letterSpacing: '0.18em',
                  color: 'var(--muted)',
                }}
              >
                NIVEL ACTUAL
              </div>
              <div style={tileValue(false)}>{p ? p.band : '—'}</div>
              <div
                style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}
              >
                {p
                  ? p.is_calibrated
                    ? `${p.stable_sessions_at_band} ${
                        p.stable_sessions_at_band === 1 ? 'sesión' : 'sesiones'
                      } aquí`
                    : 'aún ajustando'
                  : 'cargando…'}
              </div>
            </div>

            <div style={{ padding: '20px 22px', background: 'var(--cream)' }}>
              <div
                style={{
                  fontFamily: 'var(--mono)',
                  fontSize: 10,
                  letterSpacing: '0.18em',
                  color: 'var(--muted)',
                }}
              >
                ÚLTIMA SESIÓN
              </div>
              <div style={tileValue(false)}>
                {latest ? formatRelative(latest.started_at) : '—'}
              </div>
              <div
                style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}
              >
                {latest ? (latest.theme_domain ?? 'conversación') : 'aún no hay'}
              </div>
            </div>
          </div>

          <div style={{ marginTop: 20 }}>
            <AgentCard />
          </div>
        </div>
      </section>

      <footer
        style={{ padding: '24px 80px 40px', borderTop: '1px solid var(--line)' }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 16,
          }}
        >
          <div
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 11,
              letterSpacing: '0.2em',
              color: 'var(--muted)',
              textTransform: 'uppercase',
            }}
          >
            Temas recientes · toca uno para retomarlo
          </div>
          <a
            onClick={() => navigate('historial')}
            style={{
              fontSize: 12,
              color: 'var(--muted)',
              cursor: 'pointer',
            }}
          >
            ver todo →
          </a>
        </div>

        {sessions.error && !isAuthError(sessions.error) ? (
          <ErrorNotice>No pude cargar tus temas recientes.</ErrorNotice>
        ) : topics.length === 0 ? (
          <Empty>
            {sessions.loading
              ? 'Cargando…'
              : 'Aún no hay temas — el primero saldrá de tu próxima conversación.'}
          </Empty>
        ) : (
          <div
            style={{ display: 'flex', gap: 12, overflowX: 'auto' }}
            className="no-scrollbar"
          >
            {topics.map((s) => {
              const duration = formatDuration(s.started_at, s.ended_at);
              const modeLabel = formatMode(s.mode);
              return (
                <div
                  key={s.session_id}
                  onClick={() => hasToken && ready && start(s.theme_domain ?? '')}
                  style={{
                    flexShrink: 0,
                    padding: '14px 18px',
                    border: '1px solid var(--line)',
                    borderRadius: 10,
                    background: 'transparent',
                    cursor: hasToken && ready ? 'pointer' : 'default',
                    minWidth: 200,
                    transition: 'all 0.2s',
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background = 'var(--cream-2)')
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = 'transparent')
                  }
                >
                  <div
                    style={{
                      fontSize: 14,
                      color: 'var(--ink)',
                      marginBottom: 6,
                    }}
                  >
                    {s.theme_domain}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      fontFamily: 'var(--mono)',
                      color: 'var(--muted)',
                      letterSpacing: '0.05em',
                    }}
                  >
                    {duration ?? 'en curso'} · {s.band_at_start}
                    {modeLabel ? ` · ${modeLabel}` : ''}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </footer>
    </AppShell>
  );
}
