import type { CSSProperties } from 'react';
import { useState } from 'react';
import OrbHalo from '../components/orb/OrbHalo';
import {
  ArrowRightIcon,
  ChevronDownIcon,
  MicIcon,
} from '../components/icons';
import { useHealth } from '../lib/health';

type Props = {
  onStart: () => void;
  error?: string;
};

const navLinkStyle: CSSProperties = {
  fontSize: 13,
  color: 'var(--ink-2)',
  cursor: 'pointer',
  textDecoration: 'none',
};

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'buenos días';
  if (h < 19) return 'buenas tardes';
  return 'buenas noches';
}

export default function Home({ onStart, error }: Props) {
  const [hover, setHover] = useState(false);
  const [toast, setToast] = useState(false);
  const [time] = useState(greeting);
  const health = useHealth();

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

  const showProximamente = () => {
    setToast(true);
    setTimeout(() => setToast(false), 1500);
  };

  return (
    <div
      style={{
        height: '100vh',
        width: '100vw',
        overflow: 'auto',
        background: 'var(--cream)',
        display: 'flex',
        flexDirection: 'column',
      }}
      className="no-scrollbar"
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '28px 48px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background:
                'radial-gradient(circle at 35% 30%, #e79872 0%, #c87454 60%, #9c4a32 100%)',
              boxShadow: 'inset 0 -4px 8px rgba(90, 30, 10, 0.3)',
            }}
          />
          <span
            style={{
              fontFamily: 'var(--serif)',
              fontSize: 22,
              letterSpacing: '-0.01em',
            }}
          >
            hable ya
          </span>
        </div>
        <nav style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
          <a onClick={showProximamente} style={navLinkStyle}>
            Progreso
          </a>
          <a style={navLinkStyle}>Historial</a>
          <a style={navLinkStyle}>Ajustes</a>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: '50%',
              background: 'var(--sand)',
              border: '1px solid var(--line)',
              display: 'grid',
              placeItems: 'center',
              fontFamily: 'var(--serif)',
              fontSize: 15,
              color: 'var(--ink-2)',
              cursor: 'pointer',
            }}
            onClick={showProximamente}
          >
            A
          </div>
        </nav>
      </header>

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
            {time},
            <br />
            {/* PLACEHOLDER: learner name; requires spec #029 (learner model) */}
            <em style={{ color: 'var(--clay-deep)' }}>Ana</em>.
          </h1>
          <p
            style={{
              fontFamily: 'var(--serif)',
              fontSize: 24,
              lineHeight: 1.4,
              color: 'var(--ink-2)',
              maxWidth: 520,
              marginBottom: error ? 20 : 56,
            }}
          >
            Cuando presiones hablar, yo te escucho. Sin botones para pensar,
            solo conversación — en el ritmo que tú necesites.
          </p>

          {error && (
            <div
              style={{
                marginBottom: 36,
                padding: '12px 16px',
                borderRadius: 10,
                background: 'rgba(168, 84, 58, 0.08)',
                border: '1px solid rgba(168, 84, 58, 0.2)',
                color: 'var(--clay-deep)',
                fontSize: 13,
                maxWidth: 520,
              }}
            >
              {error}
            </div>
          )}

          <button
            type="button"
            disabled={!ready}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
            onClick={onStart}
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
              transform: ready && hover ? 'translateY(-2px)' : 'translateY(0)',
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
              <span style={{ fontSize: 16, fontWeight: 500 }}>{ctaLabel}</span>
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

          {/* PLACEHOLDER: stats require spec #026 (sessions) + #029 (learner model) */}
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
            {[
              { label: 'RACHA', value: '—', suffix: 'días', serif: true },
              { label: 'NIVEL ACTUAL', value: 'A2', sub: 'inicial' },
              { label: 'ÚLTIMA SESIÓN', value: '—', sub: 'aún no hay' },
            ].map((s, i) => (
              <div
                key={i}
                style={{ padding: '20px 22px', background: 'var(--cream)' }}
              >
                <div
                  style={{
                    fontFamily: 'var(--mono)',
                    fontSize: 10,
                    letterSpacing: '0.18em',
                    color: 'var(--muted)',
                  }}
                >
                  {s.label}
                </div>
                <div
                  style={{
                    fontFamily: s.serif ? 'var(--serif)' : 'var(--sans)',
                    fontSize: s.serif ? 36 : 22,
                    fontWeight: s.serif ? 400 : 500,
                    marginTop: 6,
                    color: 'var(--ink)',
                    letterSpacing: '-0.01em',
                  }}
                >
                  {s.value}{' '}
                  {s.suffix && (
                    <span
                      style={{
                        fontSize: 14,
                        color: 'var(--muted)',
                        fontFamily: 'var(--sans)',
                        fontWeight: 400,
                      }}
                    >
                      {s.suffix}
                    </span>
                  )}
                </div>
                {s.sub && (
                  <div
                    style={{
                      fontSize: 12,
                      color: 'var(--muted)',
                      marginTop: 4,
                    }}
                  >
                    {s.sub}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div
            style={{
              marginTop: 20,
              padding: '16px 20px',
              borderRadius: 14,
              background: 'var(--cream-2)',
              border: '1px solid var(--line)',
              display: 'flex',
              alignItems: 'center',
              gap: 14,
            }}
          >
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #c87454, #d98a63)',
                display: 'grid',
                placeItems: 'center',
                color: 'var(--cream)',
                fontFamily: 'var(--serif)',
                fontSize: 18,
              }}
            >
              M
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 500 }}>
                María · agente en español
              </div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                acento: Ciudad de México · voz cálida · ritmo medio
              </div>
            </div>
            <ChevronDownIcon size={18} stroke="var(--muted)" />
          </div>
        </div>
      </section>

      {/* PLACEHOLDER: recent topics are static; real data requires spec #026 */}
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
            Temas recientes · el agente puede sugerir o cambiar
          </div>
          <a style={{ fontSize: 12, color: 'var(--muted)' }}>ver todo →</a>
        </div>
        <div
          style={{ display: 'flex', gap: 12, overflowX: 'auto' }}
          className="no-scrollbar"
        >
          {(
            [
              ['Pedir en un restaurante', '8 min', 'A2'],
              ['Planear un viaje a Oaxaca', '12 min', 'B1'],
              ['Discutir una noticia', '15 min', 'B2'],
              ['Hablar de tu familia', '10 min', 'A2'],
              ['Negociar en el mercado', '9 min', 'B1'],
              ['Contar un sueño raro', '7 min', 'B2'],
            ] as const
          ).map(([title, dur, lvl], i) => (
            <div
              key={i}
              style={{
                flexShrink: 0,
                padding: '14px 18px',
                border: '1px solid var(--line)',
                borderRadius: 10,
                background: 'transparent',
                cursor: 'pointer',
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
              <div style={{ fontSize: 14, color: 'var(--ink)', marginBottom: 6 }}>
                {title}
              </div>
              <div
                style={{
                  fontSize: 11,
                  fontFamily: 'var(--mono)',
                  color: 'var(--muted)',
                  letterSpacing: '0.05em',
                }}
              >
                {dur} · {lvl}
              </div>
            </div>
          ))}
        </div>
      </footer>

      {toast && (
        <div
          style={{
            position: 'fixed',
            top: 80,
            right: 48,
            padding: '10px 16px',
            borderRadius: 100,
            background: 'rgba(42, 33, 26, 0.92)',
            color: 'var(--cream)',
            fontSize: 12,
            fontFamily: 'var(--mono)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            animation: 'fadeIn 0.2s ease',
            boxShadow: '0 10px 30px rgba(42, 33, 26, 0.2)',
          }}
        >
          próximamente
        </div>
      )}
    </div>
  );
}
