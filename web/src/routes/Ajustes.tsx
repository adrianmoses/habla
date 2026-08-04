// Ajustes — the learner's name, the connection, the agent, and the token.
//
// Deliberately small: whether the server is reachable, control over the token
// that #016 gates every request with, and — since #021 — the one thing about
// the learner that is theirs to set. That name panel is the only write surface
// in the SPA; before it, setting anything about the learner meant `psql`.

import { useEffect, useState } from 'react';
import AgentCard from '../components/AgentCard';
import AppShell from '../components/AppShell';
import { Eyebrow, page, Panel, PageTitle } from '../components/ui';
import { apiPatch } from '../lib/api';
import { useHealth } from '../lib/health';
import { useLearnerProfile, useSessionToken } from '../lib/learner';
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

  const profile = useLearnerProfile();
  const [name, setName] = useState('');
  const [storedName, setStoredName] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);

  // `profile.data` only changes on a refetch (mount, or a token change), so
  // seeding the draft from it cannot stomp on typing mid-edit.
  useEffect(() => {
    if (profile.data) {
      setStoredName(profile.data.display_name);
      setName(profile.data.display_name ?? '');
    }
  }, [profile.data]);

  const nameDirty = name.trim() !== (storedName ?? '');

  const saveName = async () => {
    setNameError(null);
    try {
      // An emptied field is a deliberate clear, so it goes as an explicit
      // null — "sin nombre" has to stay reachable from here.
      const trimmed = name.trim();
      const res = await apiPatch<{ display_name: string | null }>(
        '/api/learner',
        { display_name: trimmed === '' ? null : trimmed },
      );
      setStoredName(res.display_name);
      setName(res.display_name ?? '');
      setNameSaved(true);
      setTimeout(() => setNameSaved(false), 1600);
    } catch {
      // A 401 already cleared the token inside `apiPatch`; App's auth guard
      // takes it from there. Anything else is worth saying out loud.
      setNameError('No se pudo guardar. Inténtalo otra vez.');
    }
  };

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
          subtitle="Tu nombre, la conexión, la voz de María y tu token de acceso."
        />

        <div style={{ display: 'grid', gap: 24 }}>
          <Panel>
            <Eyebrow>Tu nombre</Eyebrow>
            <div style={{ display: 'flex', gap: 10 }}>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && nameDirty) void saveName();
                }}
                placeholder="Sin nombre"
                maxLength={40}
                autoComplete="off"
                style={{
                  flex: 1,
                  padding: '13px 15px',
                  borderRadius: 12,
                  border: '1px solid var(--line)',
                  background: 'var(--cream-2)',
                  color: 'var(--ink)',
                  fontFamily: 'var(--sans)',
                  fontSize: 14,
                  outline: 'none',
                }}
              />
              <button
                type="button"
                onClick={() => void saveName()}
                disabled={!nameDirty}
                style={{
                  padding: '13px 20px',
                  borderRadius: 12,
                  border: 'none',
                  background: nameDirty ? 'var(--ink)' : 'var(--muted)',
                  color: 'var(--cream)',
                  fontFamily: 'var(--sans)',
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: nameDirty ? 'pointer' : 'not-allowed',
                }}
              >
                Guardar
              </button>
            </div>
            <div
              style={{
                fontSize: 12,
                color: nameError ? 'var(--clay-deep)' : 'var(--muted)',
                fontFamily: nameSaved ? 'var(--mono)' : 'var(--sans)',
                letterSpacing: nameSaved ? '0.04em' : undefined,
                marginTop: 14,
              }}
            >
              {nameError ??
                (nameSaved
                  ? 'guardado'
                  : 'Así te saluda la app. Déjalo vacío si prefieres que no te nombre.')}
            </div>
          </Panel>

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
