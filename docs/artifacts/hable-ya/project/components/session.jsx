// Active session — ambient, waveform-driven, breathing orb centerpiece
const { useState: useStateSession, useEffect: useEffectSession, useRef: useRefSession } = React;

// simulated conversation script for demo
const SCRIPT = [
  { who: 'agent', es: 'Hola Ana, ¿cómo estás hoy? Me gustaría saber qué hiciste el fin de semana.',
    en: 'Hi Ana, how are you today? I\'d like to know what you did over the weekend.' },
  { who: 'user', es: 'Hola María. Bien, gracias. Fui... fui a la playa con mi familia.',
    en: 'Hi María. Good, thanks. I went... I went to the beach with my family.' },
  { who: 'agent', es: '¡Qué bonito! ¿A qué playa fueron? ¿Y cómo estuvo el clima?',
    en: 'How lovely! Which beach did you go to? And how was the weather?' },
  { who: 'user', es: 'Fuimos a Sayulita. El clima estuvo... muy caliente pero agradable.',
    en: 'We went to Sayulita. The weather was... very hot but pleasant.',
    hint: { word: 'caliente', suggest: 'caluroso', note: 'para clima, prueba "caluroso"' } },
  { who: 'agent', es: 'Perfecto, "caluroso" suena más natural para hablar del clima. ¿Hicieron algo especial allá?',
    en: 'Perfect, "caluroso" sounds more natural for weather. Did you do anything special there?' },
  { who: 'user', es: 'Sí, mis hijos aprendieron a surfear y yo leí tres libros en la hamaca.',
    en: 'Yes, my kids learned to surf and I read three books in the hammock.' },
  { who: 'agent', es: '¡Tres libros! Eso sí que es unas vacaciones relajadas. ¿Qué libro te gustó más?',
    en: 'Three books! Now that\'s a relaxed vacation. Which book did you like the most?',
    pivot: { from: 'A2 · vacaciones', to: 'B1 · literatura', reason: 'respuestas más largas y fluidas' } },
];

function Session({ onEnd, variant = 'A', transcript: showTranscript = true, difficultyIndicator = 'subtle' }) {
  const [turn, setTurn] = useStateSession(0);
  const [speaker, setSpeaker] = useStateSession('agent'); // 'user' | 'agent' | 'idle'
  const [displayed, setDisplayed] = useStateSession(0); // chars displayed in caption (typewriter)
  const [elapsedSec, setElapsedSec] = useStateSession(0);
  const [paused, setPaused] = useStateSession(false);
  const [currentLevel, setCurrentLevel] = useStateSession('A2');
  const [showPivot, setShowPivot] = useStateSession(false);

  // timer
  useEffectSession(() => {
    if (paused) return;
    const id = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [paused]);

  // autoplay through script
  useEffectSession(() => {
    if (paused) return;
    const current = SCRIPT[turn];
    if (!current) return;
    setSpeaker(current.who);
    setDisplayed(0);

    // typewriter
    let i = 0;
    const typeId = setInterval(() => {
      i += 2;
      setDisplayed(i);
      if (i >= current.es.length) clearInterval(typeId);
    }, 28);

    // after read time, advance
    const readMs = Math.max(2400, current.es.length * 55);
    const advanceId = setTimeout(() => {
      if (current.pivot) {
        setShowPivot(true);
        setTimeout(() => {
          setCurrentLevel('B1');
          setShowPivot(false);
          setTurn((t) => (t + 1) % SCRIPT.length);
        }, 2600);
      } else {
        setTurn((t) => (t + 1) % SCRIPT.length);
      }
    }, readMs);

    return () => { clearInterval(typeId); clearTimeout(advanceId); };
  }, [turn, paused]);

  const current = SCRIPT[turn] || SCRIPT[0];
  const caption = current.es.slice(0, displayed);
  const mm = String(Math.floor(elapsedSec / 60)).padStart(2, '0');
  const ss = String(elapsedSec % 60).padStart(2, '0');

  return (
    <div style={{
      height: '100vh', width: '100vw', overflow: 'hidden',
      position: 'relative',
      background: 'radial-gradient(ellipse at 50% 40%, #f0e6d4 0%, #e8dcc4 60%, #dfd0b2 100%)',
    }}>
      {/* subtle grain */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        opacity: 0.4,
        backgroundImage: 'radial-gradient(rgba(107, 70, 40, 0.06) 1px, transparent 1px)',
        backgroundSize: '3px 3px',
      }} />

      {/* top status bar */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0,
        padding: '22px 40px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{
            width: 10, height: 10, borderRadius: '50%',
            background: paused ? 'var(--muted)' : '#c87454',
            boxShadow: paused ? 'none' : '0 0 0 4px rgba(200, 116, 84, 0.2)',
            animation: paused ? 'none' : 'pulse 2s infinite',
          }} />
          <span style={{
            fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.2em',
            textTransform: 'uppercase', color: 'var(--ink-2)',
          }}>
            {paused ? 'PAUSADO' : 'MICRÓFONO ACTIVO'}
          </span>
          <span style={{
            fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)',
            paddingLeft: 14, marginLeft: 4,
            borderLeft: '1px solid var(--line)',
          }}>
            {mm}:{ss} / 12:00
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {/* difficulty badge */}
          <div style={{
            padding: '6px 12px',
            borderRadius: 100,
            background: 'rgba(42, 33, 26, 0.06)',
            border: '1px solid var(--line)',
            display: 'flex', alignItems: 'center', gap: 8,
            fontSize: 12,
            fontFamily: 'var(--mono)',
            letterSpacing: '0.08em',
          }}>
            <span style={{ opacity: 0.5 }}>NIVEL</span>
            <span style={{ color: 'var(--clay-deep)', fontWeight: 500 }}>{currentLevel}</span>
          </div>
          <button onClick={() => setPaused(!paused)} style={iconBtn}>
            {paused ? <PlayIcon size={16} /> : <PauseIcon size={16} />}
          </button>
          <button onClick={onEnd} style={{ ...iconBtn, background: 'rgba(168, 84, 58, 0.1)', color: 'var(--clay-deep)' }}>
            <CloseIcon size={16} />
          </button>
        </div>
      </div>

      {/* center: orb */}
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        gap: 50,
      }}>
        {/* "agent speaking" label above */}
        <div style={{
          position: 'absolute', top: '18%',
          fontFamily: 'var(--mono)', fontSize: 11,
          letterSpacing: '0.25em', textTransform: 'uppercase',
          color: 'var(--muted)',
          opacity: speaker === 'idle' ? 0.3 : 0.75,
          transition: 'opacity 0.3s',
        }}>
          {speaker === 'agent' ? 'maría · hablando' : speaker === 'user' ? 'tú · hablando' : 'escuchando'}
        </div>

        <Orb variant={variant} speaker={paused ? 'idle' : speaker} size={460} />

        {/* caption under orb */}
        {showTranscript && (
          <div style={{
            width: '80%', maxWidth: 860,
            minHeight: 140, // reserve space
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', gap: 14,
            textAlign: 'center',
            padding: '0 20px',
          }}>
            <div style={{
              fontFamily: 'var(--serif)',
              fontSize: 38, lineHeight: 1.25,
              letterSpacing: '-0.015em',
              color: speaker === 'user' ? 'var(--ink)' : 'var(--ink-2)',
              fontStyle: speaker === 'user' ? 'italic' : 'normal',
              transition: 'color 0.4s',
            }}>
              {speaker === 'user' && <span style={{ opacity: 0.4, marginRight: 6 }}>“</span>}
              {caption}
              <span style={{
                display: 'inline-block', width: 2, height: 26,
                background: 'var(--clay)',
                marginLeft: 6, verticalAlign: 'middle',
                opacity: displayed < current.es.length ? 1 : 0,
                animation: 'blink 1s infinite',
              }} />
              {speaker === 'user' && displayed >= current.es.length && <span style={{ opacity: 0.4, marginLeft: 6 }}>”</span>}
            </div>

            {/* subtle hint when one is present */}
            {current.hint && displayed >= current.es.length && speaker === 'user' && (
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '6px 14px',
                background: 'rgba(200, 116, 84, 0.1)',
                border: '1px solid rgba(200, 116, 84, 0.25)',
                borderRadius: 100,
                fontSize: 13,
                color: 'var(--clay-deep)',
                fontFamily: 'var(--sans)',
                animation: 'fadeIn 0.4s ease',
              }}>
                <SparkIcon size={12} />
                <span>
                  <span style={{ textDecoration: 'line-through', opacity: 0.5 }}>{current.hint.word}</span>
                  {' → '}
                  <span style={{ fontWeight: 500 }}>{current.hint.suggest}</span>
                  <span style={{ opacity: 0.65, marginLeft: 6 }}>· {current.hint.note}</span>
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* bottom: ambient controls */}
      <div style={{
        position: 'absolute', bottom: 24, left: 0, right: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        gap: 16,
        zIndex: 10,
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          padding: '10px 16px 10px 14px',
          background: 'rgba(255, 253, 248, 0.7)',
          backdropFilter: 'blur(16px)',
          border: '1px solid var(--line)',
          borderRadius: 100,
          boxShadow: '0 4px 20px rgba(42, 33, 26, 0.06)',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '4px 10px',
            borderRadius: 100,
            background: 'rgba(42, 33, 26, 0.04)',
          }}>
            <MicIcon size={13} stroke="var(--clay)" />
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-2)', letterSpacing: '0.08em' }}>
              SIEMPRE ABIERTO
            </span>
          </div>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>habla cuando quieras — te escucho sin presionar nada</span>
        </div>
      </div>

      {/* pivot announcement overlay */}
      {showPivot && (
        <div style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          padding: '28px 40px',
          background: 'rgba(42, 33, 26, 0.92)',
          backdropFilter: 'blur(20px)',
          color: 'var(--cream)',
          borderRadius: 20,
          zIndex: 30,
          animation: 'fadeIn 0.3s ease',
          boxShadow: '0 30px 80px rgba(42, 33, 26, 0.3)',
          maxWidth: 420,
          textAlign: 'center',
        }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.22em', opacity: 0.6, marginBottom: 10 }}>
            · AJUSTANDO LA CONVERSACIÓN ·
          </div>
          <div style={{ fontFamily: 'var(--serif)', fontSize: 24, lineHeight: 1.3, marginBottom: 12 }}>
            Vamos a subir un nivel. Tu español se siente cómodo hoy.
          </div>
          <div style={{ fontSize: 12, opacity: 0.55, fontFamily: 'var(--mono)', letterSpacing: '0.05em' }}>
            A2 · vacaciones &nbsp;→&nbsp; B1 · literatura
          </div>
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 0 4px rgba(200, 116, 84, 0.2); }
          50% { box-shadow: 0 0 0 10px rgba(200, 116, 84, 0.05); }
        }
        @keyframes blink { 50% { opacity: 0; } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>
    </div>
  );
}

const iconBtn = {
  width: 36, height: 36, borderRadius: '50%',
  background: 'rgba(42, 33, 26, 0.06)',
  border: '1px solid var(--line)',
  color: 'var(--ink-2)',
  display: 'grid', placeItems: 'center',
  cursor: 'pointer',
  padding: 0,
};

Object.assign(window, { Session });
