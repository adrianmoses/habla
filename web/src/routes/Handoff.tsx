// `/session/:id` — the La Libreta pre-session view (spec #033).
//
// The screen exists to make an external deep link *safe*. Arriving here from
// another app, a bookmark, or a reload resolves one JSON document and stops:
// the microphone, the WebSocket and every paid API call are behind the start
// button, and nothing on this page reaches them (spec Key Decision 5).
//
// It also owns the four ways the link can fail to become a session — still
// loading, no session token yet, an id the server doesn't know, and a server
// that would not answer — because a deep link that silently redirected to Home
// would look identical to one that worked.

import AppShell from '../components/AppShell';
import { MicIcon } from '../components/icons';
import { Empty, ErrorNotice, Eyebrow, Panel, TokenPrompt, page } from '../components/ui';
import { renderableFields, startRequestFor, useHandoff } from '../lib/handoff';
import { navigate } from '../lib/router';
import type { SessionRequest } from '../voice/types';

type Props = {
  id: string | null;
  onStart: (request: SessionRequest) => void;
  ready: boolean;
};

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <AppShell current="handoff">
      <section style={{ ...page, maxWidth: 780 }}>{children}</section>
    </AppShell>
  );
}

export default function Handoff({ id, onStart, ready }: Props) {
  const state = useHandoff(id);

  if (state.status === 'loading') {
    return (
      <Frame>
        <Eyebrow>La Libreta</Eyebrow>
        <Empty>Buscando la consigna…</Empty>
      </Frame>
    );
  }

  if (state.status === 'needs-token') {
    return (
      <Frame>
        <Eyebrow>La Libreta</Eyebrow>
        <h1
          style={{
            fontFamily: 'var(--serif)',
            fontWeight: 400,
            fontSize: 44,
            lineHeight: 1.1,
            color: 'var(--ink)',
            marginBottom: 14,
          }}
        >
          Introduce tu token para continuar
        </h1>
        <p
          style={{
            fontFamily: 'var(--serif)',
            fontSize: 19,
            color: 'var(--ink-2)',
            maxWidth: 560,
            marginBottom: 26,
          }}
        >
          Esta práctica te está esperando. Guarda el token y la abrimos aquí
          mismo — no perderás el enlace.
        </p>
        <TokenPrompt />
      </Frame>
    );
  }

  if (state.status === 'not-found' || state.status === 'error') {
    const missing = state.status === 'not-found';
    return (
      <Frame>
        <Eyebrow>La Libreta</Eyebrow>
        <h1
          style={{
            fontFamily: 'var(--serif)',
            fontWeight: 400,
            fontSize: 44,
            lineHeight: 1.1,
            color: 'var(--ink)',
            marginBottom: 18,
          }}
        >
          {missing ? 'No encontré esta práctica' : 'No pude cargar la práctica'}
        </h1>
        <div style={{ maxWidth: 560, marginBottom: 26 }}>
          <ErrorNotice>
            {missing
              ? 'El enlace no corresponde a ninguna sesión. Vuelve a enviarla desde La Libreta.'
              : 'El servidor no respondió. Inténtalo de nuevo en un momento.'}
          </ErrorNotice>
        </div>
        <button
          type="button"
          onClick={() => navigate('home')}
          style={{
            padding: '13px 22px',
            borderRadius: 100,
            border: '1px solid var(--line)',
            background: 'transparent',
            color: 'var(--ink-2)',
            fontFamily: 'var(--sans)',
            fontSize: 14,
            cursor: 'pointer',
          }}
        >
          Ir al inicio
        </button>
      </Frame>
    );
  }

  const { handoff } = state;
  const { text, structures, target } = renderableFields(handoff);
  const done = handoff.completedAt !== null;

  return (
    <Frame>
      <Eyebrow>
        La Libreta · {handoff.date} · {handoff.sourceRef}
      </Eyebrow>
      <h1
        style={{
          fontFamily: 'var(--serif)',
          fontWeight: 400,
          fontSize: 40,
          lineHeight: 1.1,
          letterSpacing: '-0.02em',
          color: 'var(--ink)',
          marginBottom: 24,
        }}
      >
        Práctica de expresión oral
      </h1>

      {/* Verbatim, in the learner's own reading order: consigna, then the
          structures to reach for, then the shape of the answer. */}
      <Panel style={{ marginBottom: 20 }}>
        <div
          style={{
            fontFamily: 'var(--serif)',
            fontSize: 23,
            lineHeight: 1.45,
            color: 'var(--ink)',
            whiteSpace: 'pre-wrap',
          }}
        >
          {text}
        </div>
      </Panel>

      {structures.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <Eyebrow>Estructuras</Eyebrow>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {structures.map((structure) => (
              <span
                key={structure}
                style={{
                  padding: '7px 13px',
                  borderRadius: 100,
                  border: '1px solid rgba(168, 84, 58, 0.25)',
                  background: 'rgba(200, 116, 84, 0.1)',
                  color: 'var(--clay-deep)',
                  fontSize: 13,
                }}
              >
                {structure}
              </span>
            ))}
          </div>
        </div>
      )}

      {target && (
        <div style={{ marginBottom: 30 }}>
          <Eyebrow>Formato</Eyebrow>
          <div style={{ fontSize: 15, color: 'var(--ink-2)' }}>{target}</div>
        </div>
      )}

      {done && (
        <div style={{ maxWidth: 560, marginBottom: 22 }}>
          <ErrorNotice>
            Ya marcaste esta práctica como terminada. Puedes repetirla, pero
            solo se registra una vez.
          </ErrorNotice>
        </div>
      )}

      <button
        type="button"
        disabled={!ready}
        onClick={() => onStart(startRequestFor(handoff))}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          padding: '18px 26px 18px 18px',
          borderRadius: 100,
          background: ready ? 'var(--ink)' : 'var(--muted)',
          color: 'var(--cream)',
          border: 'none',
          cursor: ready ? 'pointer' : 'not-allowed',
          opacity: ready ? 1 : 0.75,
          fontFamily: 'var(--sans)',
          fontSize: 15,
          boxShadow: '0 10px 30px rgba(42, 33, 26, 0.18)',
        }}
      >
        <span
          style={{
            width: 42,
            height: 42,
            borderRadius: '50%',
            background: 'var(--clay)',
            display: 'grid',
            placeItems: 'center',
          }}
        >
          <MicIcon size={19} stroke="var(--cream)" />
        </span>
        <span
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-start',
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 500 }}>
            {ready ? 'Empezar la práctica' : 'María está despertando…'}
          </span>
          <span
            style={{
              fontSize: 12,
              opacity: 0.6,
              fontFamily: 'var(--mono)',
              letterSpacing: '0.1em',
            }}
          >
            {ready ? 'EL MICRÓFONO SE ACTIVA AL PULSAR' : 'ESPERANDO AL SERVIDOR…'}
          </span>
        </span>
      </button>
    </Frame>
  );
}
