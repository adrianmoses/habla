// Recap — session summary with 3 variants
const { useState: useStateRecap } = React;

const RECAP_DATA = {
  duration: '12:34',
  words: 287,
  turns: 24,
  newWords: ['caluroso', 'hamaca', 'sayulita', 'surfear', 'agradable', 'relajadas'],
  level: { from: 'A2', to: 'B1.1', trend: '+0.4' },
  topics: ['vacaciones en familia', 'literatura ligera', 'planes para el verano'],
  strengths: ['Usaste el pretérito con confianza', 'Mantuviste turnos largos (avg. 18s)', 'Vocabulario de viaje sólido'],
  corrections: [
    { wrong: 'muy caliente', right: 'muy caluroso', context: 'para hablar del clima' },
    { wrong: 'yo fui a leer', right: 'yo leí', context: 'el pretérito directo es más natural' },
    { wrong: 'ellos aprendieron surfear', right: 'ellos aprendieron a surfear', context: 'aprender + a + infinitivo' },
  ],
  moment: {
    es: '"Mis hijos aprendieron a surfear y yo leí tres libros en la hamaca."',
    en: '"My kids learned to surf and I read three books in the hammock."',
    note: 'respuesta espontánea con dos ideas conectadas — nivel B1',
  },
};

// VARIANT A: editorial, calm, vertical scroll with the "moment" as hero
function RecapA({ onDone }) {
  return (
    <div style={{ height: '100vh', width: '100vw', overflow: 'auto', background: 'var(--cream)' }} className="no-scrollbar">
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '48px 48px 80px' }}>
        {/* header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 60 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', color: 'var(--muted)' }}>
            SESIÓN · MARTES 15 ABRIL · 14:02
          </div>
          <button onClick={onDone} style={{ ...plainBtn }}>cerrar ✕</button>
        </div>

        {/* hero headline */}
        <div style={{ marginBottom: 48 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', color: 'var(--clay)', marginBottom: 14 }}>
            ● SUBISTE DE NIVEL
          </div>
          <h1 style={{
            fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 72,
            lineHeight: 1.05, letterSpacing: '-0.025em', color: 'var(--ink)',
            marginBottom: 14,
          }}>
            Hoy sonaste más <em style={{ color: 'var(--clay-deep)' }}>segura</em>. Lo oí en los silencios.
          </h1>
          <p style={{ fontFamily: 'var(--serif)', fontSize: 22, lineHeight: 1.5, color: 'var(--ink-2)', maxWidth: 640 }}>
            Tus pausas bajaron a la mitad. Hiciste oraciones más largas sin perder el hilo.
            Por eso, a mitad de la conversación, subí el nivel a <strong style={{ fontWeight: 500 }}>B1.1</strong>.
          </p>
        </div>

        {/* stats strip */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
          border: '1px solid var(--line)', borderRadius: 14,
          marginBottom: 56, overflow: 'hidden', background: 'var(--cream-2)',
        }}>
          {[
            { k: 'DURACIÓN', v: RECAP_DATA.duration, sub: 'minutos' },
            { k: 'PALABRAS', v: RECAP_DATA.words, sub: 'dichas por ti' },
            { k: 'TURNOS', v: RECAP_DATA.turns, sub: 'intercambios' },
            { k: 'NIVEL', v: RECAP_DATA.level.to, sub: `de ${RECAP_DATA.level.from} · ${RECAP_DATA.level.trend}` },
          ].map((s, i) => (
            <div key={i} style={{
              padding: '22px 24px',
              borderRight: i < 3 ? '1px solid var(--line)' : 'none',
            }}>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--muted)' }}>{s.k}</div>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 38, color: 'var(--ink)', marginTop: 6, letterSpacing: '-0.01em' }}>{s.v}</div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>{s.sub}</div>
            </div>
          ))}
        </div>

        {/* moment */}
        <div style={{ marginBottom: 56 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.18em', color: 'var(--muted)', marginBottom: 14, textTransform: 'uppercase' }}>
            Un momento que me gustó
          </div>
          <blockquote style={{
            fontFamily: 'var(--serif)', fontSize: 38, lineHeight: 1.35,
            color: 'var(--ink)', fontStyle: 'italic',
            paddingLeft: 24, borderLeft: '3px solid var(--clay)',
            letterSpacing: '-0.01em',
          }}>
            {RECAP_DATA.moment.es}
          </blockquote>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 14, paddingLeft: 27 }}>
            {RECAP_DATA.moment.note}
          </div>
        </div>

        {/* two columns: strengths + corrections */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, marginBottom: 56 }}>
          <div>
            <div style={sectionLabel}>LO QUE FUNCIONÓ</div>
            <ul style={{ listStyle: 'none' }}>
              {RECAP_DATA.strengths.map((s, i) => (
                <li key={i} style={{
                  padding: '14px 0', borderBottom: i < RECAP_DATA.strengths.length - 1 ? '1px solid var(--line)' : 'none',
                  fontSize: 16, lineHeight: 1.5, color: 'var(--ink)',
                  display: 'flex', gap: 12,
                }}>
                  <CheckIcon size={18} stroke="var(--clay)" style={{ flexShrink: 0, marginTop: 3 }} />
                  {s}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div style={sectionLabel}>PARA PULIR (3)</div>
            <ul style={{ listStyle: 'none' }}>
              {RECAP_DATA.corrections.map((c, i) => (
                <li key={i} style={{
                  padding: '14px 0', borderBottom: i < RECAP_DATA.corrections.length - 1 ? '1px solid var(--line)' : 'none',
                }}>
                  <div style={{ fontSize: 15, color: 'var(--ink)', marginBottom: 4 }}>
                    <span style={{ textDecoration: 'line-through', color: 'var(--muted)' }}>{c.wrong}</span>
                    <span style={{ margin: '0 8px', color: 'var(--clay)' }}>→</span>
                    <span style={{ fontWeight: 500 }}>{c.right}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{c.context}</div>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* new words */}
        <div style={{ marginBottom: 56 }}>
          <div style={sectionLabel}>PALABRAS NUEVAS · 6</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {RECAP_DATA.newWords.map((w) => (
              <span key={w} style={{
                padding: '8px 14px', borderRadius: 100,
                background: 'var(--sand)', color: 'var(--ink-2)',
                fontSize: 14, fontFamily: 'var(--serif)', letterSpacing: '-0.005em',
              }}>{w}</span>
            ))}
          </div>
        </div>

        {/* cta */}
        <div style={{ display: 'flex', gap: 12 }}>
          <button style={{ ...primaryBtn }} onClick={onDone}>Hacer otra ronda</button>
          <button style={{ ...plainBtn, padding: '14px 22px', border: '1px solid var(--line)' }}>Guardar y salir</button>
        </div>
      </div>
    </div>
  );
}

// VARIANT B: scorecard grid — more dashboard-y, quick scan
function RecapB({ onDone }) {
  return (
    <div style={{ height: '100vh', width: '100vw', overflow: 'auto', background: 'var(--ink)', color: 'var(--cream)' }} className="no-scrollbar">
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '40px 48px 80px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 36 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', opacity: 0.5 }}>
            RECAP · MARTES 15 ABRIL
          </div>
          <button onClick={onDone} style={{ ...plainBtn, color: 'var(--cream)' }}>cerrar ✕</button>
        </div>

        <h1 style={{
          fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 80,
          lineHeight: 1, letterSpacing: '-0.03em', marginBottom: 10,
        }}>
          <span style={{ color: 'var(--terra)' }}>B1.1</span>
          <span style={{ opacity: 0.3, margin: '0 18px', fontSize: 48 }}>from</span>
          <span style={{ opacity: 0.55 }}>A2</span>
        </h1>
        <p style={{ fontFamily: 'var(--serif)', fontSize: 22, opacity: 0.7, marginBottom: 48 }}>
          Ajusté el nivel a mitad de la conversación. Estás lista para más.
        </p>

        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)',
          gap: 16, marginBottom: 36,
        }}>
          {/* large card: fluency curve */}
          <div style={{ ...darkCard, gridColumn: 'span 8', padding: 28 }}>
            <div style={darkLabel}>FLUIDEZ · POR MINUTO</div>
            <svg width="100%" height="140" viewBox="0 0 400 140" style={{ marginTop: 12 }}>
              <defs>
                <linearGradient id="fluency" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#d98a63" stopOpacity="0.5"/>
                  <stop offset="100%" stopColor="#d98a63" stopOpacity="0"/>
                </linearGradient>
              </defs>
              {(() => {
                const pts = [0.35, 0.42, 0.5, 0.48, 0.62, 0.68, 0.72, 0.75, 0.82, 0.78, 0.88, 0.92];
                const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${(i/(pts.length-1))*380 + 10} ${130 - p * 110}`).join(' ');
                const fill = d + ` L 390 130 L 10 130 Z`;
                return <>
                  <path d={fill} fill="url(#fluency)" />
                  <path d={d} stroke="#d98a63" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                  {pts.map((p, i) => (
                    <circle key={i} cx={(i/(pts.length-1))*380 + 10} cy={130 - p * 110} r="3" fill="#d98a63"/>
                  ))}
                  {/* pivot line at min 6 */}
                  <line x1={(5/11)*380 + 10} x2={(5/11)*380 + 10} y1="10" y2="130" stroke="#c87454" strokeDasharray="3 4" strokeWidth="1" opacity="0.6"/>
                  <text x={(5/11)*380 + 16} y="24" fill="#d98a63" fontFamily="var(--mono)" fontSize="9" letterSpacing="0.1em">PIVOTE → B1</text>
                </>;
              })()}
            </svg>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'var(--mono)', opacity: 0.5, letterSpacing: '0.08em', marginTop: 6 }}>
              <span>0:00</span><span>3:00</span><span>6:00</span><span>9:00</span><span>12:34</span>
            </div>
          </div>

          <div style={{ ...darkCard, gridColumn: 'span 4', padding: 28 }}>
            <div style={darkLabel}>TIEMPO HABLADO</div>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 64, marginTop: 8, lineHeight: 1 }}>58<span style={{ fontSize: 22, opacity: 0.5 }}>%</span></div>
            <div style={{ fontSize: 12, opacity: 0.6, marginTop: 8 }}>tú hablaste más que yo — perfecto</div>
            <div style={{
              height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 100, marginTop: 20, overflow: 'hidden',
            }}>
              <div style={{ width: '58%', height: '100%', background: 'var(--terra)' }} />
            </div>
          </div>

          {[
            { k: 'PALABRAS DICHAS', v: '287', sub: '+32 vs. promedio' },
            { k: 'VOCABULARIO NUEVO', v: '6', sub: 'caluroso, hamaca...' },
            { k: 'CORRECCIONES', v: '3', sub: 'todas sutiles' },
            { k: 'PAUSA PROMEDIO', v: '1.4s', sub: '−0.8s vs. martes' },
          ].map((s, i) => (
            <div key={i} style={{ ...darkCard, gridColumn: 'span 3', padding: 22 }}>
              <div style={darkLabel}>{s.k}</div>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 40, marginTop: 6 }}>{s.v}</div>
              <div style={{ fontSize: 12, opacity: 0.55, marginTop: 4 }}>{s.sub}</div>
            </div>
          ))}

          <div style={{ ...darkCard, gridColumn: 'span 7', padding: 28 }}>
            <div style={darkLabel}>CORRECCIONES</div>
            <div style={{ marginTop: 12 }}>
              {RECAP_DATA.corrections.map((c, i) => (
                <div key={i} style={{
                  display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 16, alignItems: 'center',
                  padding: '12px 0',
                  borderBottom: i < RECAP_DATA.corrections.length - 1 ? '1px solid rgba(255,255,255,0.08)' : 'none',
                }}>
                  <div style={{ fontSize: 15, opacity: 0.5, textDecoration: 'line-through', fontStyle: 'italic' }}>{c.wrong}</div>
                  <ArrowRightIcon size={14} stroke="var(--terra)" />
                  <div>
                    <div style={{ fontSize: 15, color: 'var(--cream)' }}>{c.right}</div>
                    <div style={{ fontSize: 11, opacity: 0.5, marginTop: 2 }}>{c.context}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ ...darkCard, gridColumn: 'span 5', padding: 28, display: 'flex', flexDirection: 'column' }}>
            <div style={darkLabel}>MOMENTO DESTACADO</div>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 22, lineHeight: 1.4, marginTop: 12, fontStyle: 'italic', flex: 1 }}>
              {RECAP_DATA.moment.es}
            </div>
            <button style={{ ...darkPillBtn, marginTop: 18, alignSelf: 'flex-start' }}>
              <PlayIcon size={12} /> escuchar 0:18
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          <button style={{ ...primaryBtn, background: 'var(--clay)' }} onClick={onDone}>Hacer otra ronda</button>
          <button style={{ ...plainBtn, color: 'var(--cream)', padding: '14px 22px', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 100 }}>Guardar y salir</button>
        </div>
      </div>
    </div>
  );
}

// VARIANT C: single-focus "letter from María" — copy-first, intimate
function RecapC({ onDone }) {
  return (
    <div style={{
      height: '100vh', width: '100vw', overflow: 'auto',
      background: 'radial-gradient(ellipse at 50% 30%, #f0e6d4 0%, #e2d4bc 100%)',
    }} className="no-scrollbar">
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '60px 48px 80px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 40 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: '50%',
              background: 'linear-gradient(135deg, #c87454, #d98a63)',
              display: 'grid', placeItems: 'center',
              color: 'var(--cream)', fontFamily: 'var(--serif)', fontSize: 16,
            }}>M</div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 500 }}>María</div>
              <div style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)', letterSpacing: '0.08em' }}>AGENTE · ES-MX</div>
            </div>
          </div>
          <button onClick={onDone} style={{ ...plainBtn }}>✕</button>
        </div>

        <div style={{ fontFamily: 'var(--serif)', fontSize: 24, lineHeight: 1.6, color: 'var(--ink)' }}>
          <p style={{ fontStyle: 'italic', color: 'var(--muted)', fontSize: 14, fontFamily: 'var(--mono)', letterSpacing: '0.12em', marginBottom: 28, textTransform: 'uppercase' }}>
            Martes · 12:34 · B1.1
          </p>

          <p style={{ marginBottom: 24 }}>
            Ana,
          </p>
          <p style={{ marginBottom: 24 }}>
            Hoy hablaste de la playa, de tus hijos aprendiendo a surfear, de los libros que leíste en una hamaca.
            Trescientas palabras — y pocas pausas.
          </p>
          <p style={{ marginBottom: 24 }}>
            Lo que más me gustó fue esto:
          </p>
          <blockquote style={{
            fontSize: 32, lineHeight: 1.3, padding: '20px 0 20px 28px',
            borderLeft: '3px solid var(--clay)', margin: '0 0 24px 0',
            color: 'var(--clay-deep)', fontStyle: 'italic', letterSpacing: '-0.01em',
          }}>
            {RECAP_DATA.moment.es}
          </blockquote>
          <p style={{ marginBottom: 24 }}>
            Dos ideas conectadas en una sola oración, con ritmo. Por eso, a los seis minutos,{' '}
            <strong style={{ fontWeight: 500, background: 'rgba(200, 116, 84, 0.15)', padding: '0 6px', borderRadius: 4 }}>
              subí el nivel de A2 a B1
            </strong>. Quizás lo notaste: empecé a hacer preguntas más abiertas.
          </p>
          <p style={{ marginBottom: 24 }}>
            Tres cositas para la próxima: <em style={{ color: 'var(--muted)' }}>caluroso</em> en lugar de <em style={{ color: 'var(--muted)' }}>caliente</em> para el clima; el pretérito directo (<em style={{ color: 'var(--muted)' }}>leí</em>, no <em style={{ color: 'var(--muted)' }}>fui a leer</em>); y <em style={{ color: 'var(--muted)' }}>aprender a</em> + infinitivo.
          </p>
          <p style={{ marginBottom: 40 }}>
            Nos vemos mañana. Si quieres, seguimos con literatura — tengo curiosidad por esos tres libros.
          </p>
          <p style={{ fontFamily: 'var(--serif)', fontStyle: 'italic', fontSize: 28, color: 'var(--clay-deep)' }}>
            — María
          </p>
        </div>

        <div style={{ display: 'flex', gap: 12, marginTop: 48 }}>
          <button style={{ ...primaryBtn }} onClick={onDone}>Otra ronda</button>
          <button style={{ ...plainBtn, padding: '14px 22px', border: '1px solid var(--line)', borderRadius: 100 }}>Ver estadísticas →</button>
        </div>
      </div>
    </div>
  );
}

function Recap({ variant = 'A', onDone }) {
  if (variant === 'B') return <RecapB onDone={onDone} />;
  if (variant === 'C') return <RecapC onDone={onDone} />;
  return <RecapA onDone={onDone} />;
}

const sectionLabel = {
  fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em',
  color: 'var(--muted)', marginBottom: 18, textTransform: 'uppercase',
};
const primaryBtn = {
  padding: '14px 26px', borderRadius: 100,
  background: 'var(--ink)', color: 'var(--cream)',
  border: 'none', cursor: 'pointer',
  fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 500,
};
const plainBtn = {
  padding: '10px 14px', background: 'transparent',
  border: 'none', cursor: 'pointer',
  fontFamily: 'var(--sans)', fontSize: 13,
  color: 'var(--muted)',
};
const darkCard = {
  background: 'rgba(255, 255, 255, 0.04)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  borderRadius: 16,
};
const darkLabel = {
  fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.22em',
  opacity: 0.5, textTransform: 'uppercase',
};
const darkPillBtn = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  padding: '6px 12px', borderRadius: 100,
  background: 'rgba(255,255,255,0.08)',
  color: 'var(--cream)', border: '1px solid rgba(255,255,255,0.1)',
  fontSize: 11, fontFamily: 'var(--mono)', letterSpacing: '0.08em', cursor: 'pointer',
};

Object.assign(window, { Recap });
