// Profile / progress
function Profile({ onBack }) {
  const days = Array.from({ length: 84 }, (_, i) => {
    const seed = (i * 31 + 7) % 17;
    const val = i < 70 ? (seed > 12 ? 0 : seed > 9 ? 1 : seed > 5 ? 2 : 3) : (seed % 3) + 1;
    return val;
  });
  const levelHistory = [
    { date: 'Ene', lvl: 'A1.2' },
    { date: 'Feb', lvl: 'A2.0' },
    { date: 'Mar', lvl: 'A2.3' },
    { date: 'Abr', lvl: 'B1.1', highlight: true },
  ];

  return (
    <div style={{ height: '100vh', width: '100vw', overflow: 'auto', background: 'var(--cream)' }} className="no-scrollbar">
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '40px 48px 80px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 40 }}>
          <button onClick={onBack} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            background: 'transparent', border: 'none',
            fontSize: 13, color: 'var(--muted)', cursor: 'pointer',
            fontFamily: 'var(--sans)',
          }}>
            <ArrowLeftIcon size={14} /> volver
          </button>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', color: 'var(--muted)' }}>
            PROGRESO · ANA
          </div>
        </div>

        {/* hero */}
        <div style={{
          display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 32, marginBottom: 48,
          alignItems: 'start',
        }}>
          <div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', color: 'var(--muted)', marginBottom: 14 }}>
              DESDE ENERO
            </div>
            <h1 style={{
              fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 64,
              lineHeight: 1.05, letterSpacing: '-0.025em', color: 'var(--ink)',
              marginBottom: 16,
            }}>
              Pasaste de <em style={{ color: 'var(--muted)' }}>A1</em> a <em style={{ color: 'var(--clay-deep)' }}>B1.1</em> en 84 días.
            </h1>
            <p style={{ fontFamily: 'var(--serif)', fontSize: 20, color: 'var(--ink-2)', maxWidth: 500, lineHeight: 1.5 }}>
              Dos sesiones por semana, 12 minutos en promedio. Las palabras están llegando más rápido que antes.
            </p>
          </div>

          <div style={{
            padding: 28, border: '1px solid var(--line)', borderRadius: 16,
            background: 'var(--cream-2)',
          }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--muted)' }}>NIVEL ACTUAL</div>
            <div style={{ marginTop: 6 }}>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 72, color: 'var(--clay-deep)', letterSpacing: '-0.02em', lineHeight: 1 }}>B1.1</div>
              <div style={{ fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--muted)', letterSpacing: '0.1em', marginTop: 10, whiteSpace: 'nowrap' }}>+0.4 esta semana</div>
            </div>
            <div style={{ marginTop: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--muted)', letterSpacing: '0.1em', marginBottom: 6 }}>
                <span>A1</span><span>A2</span><span style={{ color: 'var(--clay)' }}>B1</span><span>B2</span><span>C1</span>
              </div>
              <div style={{ height: 6, background: 'var(--sand)', borderRadius: 100, position: 'relative' }}>
                <div style={{ width: '55%', height: '100%', background: 'var(--clay)', borderRadius: 100 }} />
                <div style={{
                  position: 'absolute', left: '55%', top: '50%', transform: 'translate(-50%, -50%)',
                  width: 14, height: 14, borderRadius: '50%',
                  background: 'var(--cream)', border: '2px solid var(--clay)',
                  boxShadow: '0 2px 8px rgba(168, 84, 58, 0.3)',
                }} />
              </div>
            </div>
          </div>
        </div>

        {/* heatmap */}
        <div style={{ marginBottom: 56 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 20 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', color: 'var(--muted)', textTransform: 'uppercase' }}>
              ACTIVIDAD · ÚLTIMOS 84 DÍAS
            </div>
            <div style={{ display: 'flex', gap: 16, alignItems: 'center', fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--muted)' }}>
              <span>menos</span>
              {[0, 1, 2, 3].map((v) => (
                <div key={v} style={{
                  width: 14, height: 14, borderRadius: 3,
                  background: heatColor(v),
                }} />
              ))}
              <span>más</span>
            </div>
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(14, 1fr)', gap: 6,
            padding: 20, border: '1px solid var(--line)', borderRadius: 14,
            background: 'var(--cream-2)',
          }}>
            {days.map((v, i) => (
              <div key={i} style={{
                aspectRatio: '1', borderRadius: 4,
                background: heatColor(v),
                transition: 'transform 0.15s',
              }} title={`día ${i + 1}`} />
            ))}
          </div>
        </div>

        {/* level journey + recent sessions */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 32 }}>
          <div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', color: 'var(--muted)', marginBottom: 18, textTransform: 'uppercase' }}>
              RECORRIDO
            </div>
            <div style={{ position: 'relative', paddingLeft: 24 }}>
              <div style={{ position: 'absolute', top: 8, bottom: 8, left: 6, width: 1, background: 'var(--line-strong)' }} />
              {levelHistory.map((l, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 16, paddingBottom: 24, position: 'relative' }}>
                  <div style={{
                    position: 'absolute', left: -24, top: 2,
                    width: 13, height: 13, borderRadius: '50%',
                    background: l.highlight ? 'var(--clay)' : 'var(--cream)',
                    border: `2px solid ${l.highlight ? 'var(--clay)' : 'var(--sand-deep)'}`,
                  }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontFamily: 'var(--serif)', fontSize: l.highlight ? 28 : 22, color: l.highlight ? 'var(--clay-deep)' : 'var(--ink)', letterSpacing: '-0.01em' }}>
                      {l.lvl}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--mono)', letterSpacing: '0.08em', marginTop: 2 }}>
                      {l.date} 2026 {l.highlight && ' · hoy'}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: '0.22em', color: 'var(--muted)', marginBottom: 18, textTransform: 'uppercase' }}>
              SESIONES RECIENTES
            </div>
            <div style={{ border: '1px solid var(--line)', borderRadius: 14, overflow: 'hidden' }}>
              {[
                { date: 'Hoy · 14:02', topic: 'Vacaciones en familia', dur: '12:34', lvl: 'A2→B1', up: true },
                { date: 'Ayer · 19:15', topic: 'Pedir en restaurante', dur: '8:20', lvl: 'A2', up: false },
                { date: 'Dom · 10:30', topic: 'Planear viaje', dur: '14:01', lvl: 'A2', up: false },
                { date: 'Vie · 18:45', topic: 'Familia y rutinas', dur: '11:12', lvl: 'A2', up: false },
                { date: 'Mié · 20:00', topic: 'Negociar en mercado', dur: '9:48', lvl: 'A1→A2', up: true },
              ].map((s, i, arr) => (
                <div key={i} style={{
                  display: 'grid', gridTemplateColumns: '1fr 2fr auto auto', gap: 16, alignItems: 'center',
                  padding: '16px 20px',
                  borderBottom: i < arr.length - 1 ? '1px solid var(--line)' : 'none',
                  background: i === 0 ? 'var(--cream-2)' : 'var(--cream)',
                }}>
                  <div style={{ fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--muted)', letterSpacing: '0.06em' }}>{s.date}</div>
                  <div style={{ fontSize: 14, color: 'var(--ink)' }}>{s.topic}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>{s.dur}</div>
                  <div style={{
                    fontSize: 11, fontFamily: 'var(--mono)', letterSpacing: '0.05em',
                    padding: '3px 8px', borderRadius: 100,
                    background: s.up ? 'rgba(200, 116, 84, 0.12)' : 'transparent',
                    color: s.up ? 'var(--clay-deep)' : 'var(--muted)',
                    border: s.up ? 'none' : '1px solid var(--line)',
                  }}>
                    {s.up && '↑ '}{s.lvl}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function heatColor(v) {
  if (v === 0) return 'rgba(42, 33, 26, 0.06)';
  if (v === 1) return 'rgba(200, 116, 84, 0.22)';
  if (v === 2) return 'rgba(200, 116, 84, 0.55)';
  return 'var(--clay-deep)';
}

Object.assign(window, { Profile });
