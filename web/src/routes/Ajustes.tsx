// Ajustes — connection, agent, and the access token.
//
// Deliberately small. The learner has no name and no configurable profile yet
// (spec #021 owns that), so this holds the two things an operator actually
// needs: whether the server is reachable, and control over the token that #016
// gates every request with. Until now the only way to drop a stale token was to
// edit sessionStorage by hand.

import { useState } from 'react';
import AgentCard from '../components/AgentCard';
import AppShell from '../components/AppShell';
import { Eyebrow, page, Panel, PageTitle } from '../components/ui';
import { useHealth } from '../lib/health';
import { useSessionToken } from '../lib/learner';
import { navigate } from '../lib/router';
import { clearSessionToken, setSessionToken } from '../lib/token';

const HEALTH_COPY: Record<string, { dot: string; text: string }> = {
  ready: { dot: '#6b8f5a', text: 'Todo listo — María puede escucharte.' },
  warming: { dot: 'var(--clay)', text: 'El servidor está despertando…' },
  unknown: { dot: 'var(--muted)', text: 'Comprobando la conexión…' },
  error: { dot: 'var(--clay-deep)', text: 'No hay conexión con el servidor.' },
};

export default function Ajustes() {
  const health = useHealth();
  const [draft, setDraft] = useState('');
  const hasToken = useSessionToken() !== undefined;
  const [saved, setSaved] = useState(false);

  const status = HEALTH_COPY[health] ?? HEALTH_COPY.unknown;

  const save = () => {
    const t = draft.trim();
    if (!t) return;
    setSessionToken(t);
    setDraft('');
    setSaved(true);
    setTimeout(() => setSaved(false), 1600);
  };

  const clear = () => {
    clearSessionToken();
    navigate('home');
  };

  return (
    <AppShell current="ajustes">
      <section style={{ ...page, maxWidth: 720 }}>
        <PageTitle
          title="Ajustes"
          subtitle="La conexión, la voz de María y tu token de acceso."
        />

        <div style={{ display: 'grid', gap: 24 }}>
          <Panel>
            <Eyebrow>Conexión</Eyebrow>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: '50%',
                  background: status?.dot ?? 'var(--muted)',
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 14, color: 'var(--ink)' }}>
                {status?.text}
              </span>
            </div>
          </Panel>

          <Panel>
            <Eyebrow>Tu agente</Eyebrow>
            <AgentCard showChevron={false} />
            <div
              style={{
                fontSize: 12,
                color: 'var(--muted)',
                marginTop: 14,
              }}
            >
              La voz se configura en el servidor, no desde aquí.
            </div>
          </Panel>

          <Panel>
            <Eyebrow>Token de acceso</Eyebrow>
            <div style={{ display: 'flex', gap: 10 }}>
              <input
                type="password"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') save();
                }}
                placeholder={
                  hasToken ? 'Reemplazar el token…' : 'Pega el token del servidor…'
                }
                autoComplete="off"
                style={{
                  flex: 1,
                  padding: '13px 15px',
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
                onClick={save}
                disabled={!draft.trim()}
                style={{
                  padding: '13px 20px',
                  borderRadius: 12,
                  border: 'none',
                  background: draft.trim() ? 'var(--ink)' : 'var(--muted)',
                  color: 'var(--cream)',
                  fontFamily: 'var(--sans)',
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: draft.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                Guardar
              </button>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 16,
                marginTop: 14,
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  color: 'var(--muted)',
                  fontFamily: 'var(--mono)',
                  letterSpacing: '0.04em',
                }}
              >
                {saved
                  ? 'guardado'
                  : 'Se guarda solo en esta pestaña · no se envía a ningún tercero.'}
              </span>
              {hasToken && (
                <button
                  type="button"
                  onClick={clear}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 100,
                    border: '1px solid rgba(168, 84, 58, 0.25)',
                    background: 'transparent',
                    color: 'var(--clay-deep)',
                    fontFamily: 'var(--sans)',
                    fontSize: 12,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                  }}
                >
                  Borrar token
                </button>
              )}
            </div>
          </Panel>
        </div>
      </section>
    </AppShell>
  );
}
