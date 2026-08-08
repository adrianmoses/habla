import type { CSSProperties } from 'react';
import { useEffect, useState } from 'react';
import OrbHalo from '../components/orb/OrbHalo';
import { CloseIcon, MicIcon, PauseIcon, PlayIcon } from '../components/icons';
import { VoiceClient } from '../voice/client';
import { useAmplitude } from '../voice/amplitude';
import { clearSessionToken, getSessionToken } from '../lib/token';
import { useCompleteHandoff } from '../lib/handoff';
import { useLearnerProfile } from '../lib/learner';
import { formatMode } from '../lib/format';
import { pushSessionEntry, useBackHandler } from '../lib/router';
import type { SessionRequest } from '../voice/types';

type ExitReason = 'user' | 'error';

type Props = {
  request: SessionRequest;
  onExit: (reason: ExitReason, msg?: string) => void;
};

const iconBtn: CSSProperties = {
  width: 36,
  height: 36,
  borderRadius: '50%',
  background: 'rgba(42, 33, 26, 0.06)',
  border: '1px solid var(--line)',
  color: 'var(--ink-2)',
  display: 'grid',
  placeItems: 'center',
  cursor: 'pointer',
  padding: 0,
};

export default function Session({ request, onExit }: Props) {
  const [paused, setPaused] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [client, setClient] = useState<VoiceClient | null>(null);

  // The band badge renders before this resolves; `A2` stays the pre-load
  // default so the chrome never flashes empty (spec Key Decision).
  const profile = useLearnerProfile();
  const band = profile.data?.band ?? 'A2';
  const modeLabel = formatMode(request.mode);

  // Spec #033, Open Question 1. A handoff-backed session gets a second exit
  // that means something different: "Terminar" reports the practice to La
  // Libreta, "Cerrar" just leaves. Keeping them apart is the whole point —
  // teardown, an error, an idle timeout and a preemption all close a session,
  // and none of them is evidence the learner did the task.
  const completion = useCompleteHandoff(request.handoff);

  // A session is not a route (spec OQ2), but Back should still leave it — this
  // gives `popstate` an entry to pop, and the handler exits cleanly.
  useEffect(() => {
    pushSessionEntry();
  }, []);
  useBackHandler(true, () => onExit('user'));

  useEffect(() => {
    const c = new VoiceClient({
      token: getSessionToken(),
      request,
      onClose: (ev) => {
        if (ev.code === 1000) return;
        if (ev.code === 1008) {
          // Rejected token — drop the stale secret so Home re-prompts.
          clearSessionToken();
          onExit('error', 'Token inválido — vuelve a ingresarlo');
          return;
        }
        onExit(
          'error',
          ev.code === 1013
            ? 'María está despertando…'
            : 'Se perdió la conexión',
        );
      },
      onError: () => onExit('error', 'Se perdió la conexión'),
    });

    c.connect()
      .then(() => setClient(c))
      .catch((err: unknown) => {
        const msg =
          err instanceof Error && err.name === 'NotAllowedError'
            ? 'Permiso de micrófono denegado'
            : 'No se pudo iniciar la sesión';
        onExit('error', msg);
      });

    return () => {
      c.disconnect('unmount').catch(() => undefined);
    };
    // onExit is stable for the session's lifetime — App only swaps routes on
    // the exit it triggers, so re-binding here would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    client?.setMuted(paused);
  }, [client, paused]);

  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [paused]);

  const { amp, speaker } = useAmplitude(client);
  const displaySpeaker = paused ? 'idle' : speaker;

  const mm = String(Math.floor(elapsedSec / 60)).padStart(2, '0');
  const ss = String(elapsedSec % 60).padStart(2, '0');

  const handleClose = () => {
    client?.disconnect('user close').catch(() => undefined);
    onExit('user');
  };

  // Completion is committed server-side before the socket goes down, but the
  // learner never waits on it: the request is fired and the session ends
  // regardless of whether La Libreta is reachable.
  const handleFinish = () => {
    void completion.complete().finally(handleClose);
  };

  return (
    <div
      style={{
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        position: 'relative',
        background:
          'radial-gradient(ellipse at 50% 40%, #f0e6d4 0%, #e8dcc4 60%, #dfd0b2 100%)',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          opacity: 0.4,
          backgroundImage:
            'radial-gradient(rgba(107, 70, 40, 0.06) 1px, transparent 1px)',
          backgroundSize: '3px 3px',
        }}
      />

      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          padding: '22px 40px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: paused ? 'var(--muted)' : '#c87454',
              boxShadow: paused ? 'none' : '0 0 0 4px rgba(200, 116, 84, 0.2)',
              animation: paused ? 'none' : 'pulse 2s infinite',
            }}
          />
          <span
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 11,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              color: 'var(--ink-2)',
            }}
          >
            {paused ? 'PAUSADO' : 'MICRÓFONO ACTIVO'}
          </span>
          <span
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 11,
              color: 'var(--muted)',
              paddingLeft: 14,
              marginLeft: 4,
              borderLeft: '1px solid var(--line)',
            }}
          >
            {mm}:{ss}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {modeLabel && (
            <div
              style={{
                padding: '6px 12px',
                borderRadius: 100,
                background: 'rgba(200, 116, 84, 0.1)',
                border: '1px solid rgba(168, 84, 58, 0.25)',
                fontSize: 11,
                fontFamily: 'var(--mono)',
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--clay-deep)',
              }}
            >
              {modeLabel}
            </div>
          )}
          <div
            style={{
              padding: '6px 12px',
              borderRadius: 100,
              background: 'rgba(42, 33, 26, 0.06)',
              border: '1px solid var(--line)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 12,
              fontFamily: 'var(--mono)',
              letterSpacing: '0.08em',
            }}
          >
            <span style={{ opacity: 0.5 }}>NIVEL</span>
            <span style={{ color: 'var(--clay-deep)', fontWeight: 500 }}>
              {band}
            </span>
          </div>
          {request.handoff && (
            <button
              type="button"
              onClick={handleFinish}
              disabled={completion.state === 'sending'}
              style={{
                padding: '8px 16px',
                borderRadius: 100,
                border: '1px solid rgba(168, 84, 58, 0.3)',
                background: 'rgba(200, 116, 84, 0.12)',
                color: 'var(--clay-deep)',
                fontFamily: 'var(--sans)',
                fontSize: 13,
                cursor: completion.state === 'sending' ? 'wait' : 'pointer',
              }}
            >
              {completion.state === 'sending'
                ? 'Terminando…'
                : 'Terminar práctica'}
            </button>
          )}
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            style={iconBtn}
            aria-label={paused ? 'Reanudar' : 'Pausar'}
          >
            {paused ? <PlayIcon size={16} /> : <PauseIcon size={16} />}
          </button>
          <button
            type="button"
            onClick={handleClose}
            style={{
              ...iconBtn,
              background: 'rgba(168, 84, 58, 0.1)',
              color: 'var(--clay-deep)',
            }}
            aria-label="Cerrar"
          >
            <CloseIcon size={16} />
          </button>
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 50,
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: '18%',
            fontFamily: 'var(--mono)',
            fontSize: 11,
            letterSpacing: '0.25em',
            textTransform: 'uppercase',
            color: 'var(--muted)',
            opacity: displaySpeaker === 'idle' ? 0.3 : 0.75,
            transition: 'opacity 0.3s',
          }}
        >
          {displaySpeaker === 'agent'
            ? 'maría · hablando'
            : displaySpeaker === 'user'
              ? 'tú · hablando'
              : 'escuchando'}
        </div>

        <OrbHalo speaker={displaySpeaker} amp={amp} size={460} />
      </div>

      <div
        style={{
          position: 'absolute',
          bottom: 24,
          left: 0,
          right: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 16,
          zIndex: 10,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '10px 16px 10px 14px',
            background: 'rgba(255, 253, 248, 0.7)',
            backdropFilter: 'blur(16px)',
            border: '1px solid var(--line)',
            borderRadius: 100,
            boxShadow: '0 4px 20px rgba(42, 33, 26, 0.06)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              borderRadius: 100,
              background: 'rgba(42, 33, 26, 0.04)',
            }}
          >
            <MicIcon size={13} stroke="var(--clay)" />
            <span
              style={{
                fontFamily: 'var(--mono)',
                fontSize: 11,
                color: 'var(--ink-2)',
                letterSpacing: '0.08em',
              }}
            >
              SIEMPRE ABIERTO
            </span>
          </div>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            habla cuando quieras — te escucho sin presionar nada
          </span>
        </div>
      </div>
    </div>
  );
}
