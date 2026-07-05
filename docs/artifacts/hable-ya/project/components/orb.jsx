// Breathing orb — the core visual metaphor.
// Uses an audio-driven pseudo-amplitude: simulates speaker turns
// with smooth sine-based "breathing" + voice bursts when AGENT or USER is speaking.

const { useState, useEffect, useRef } = React;

// simulate amplitude signal that breathes + surges when someone's talking
function useAmplitude(speaker /* 'idle' | 'user' | 'agent' */) {
  const [amp, setAmp] = useState(0.3);
  const rafRef = useRef();
  const tRef = useRef(0);
  const targetRef = useRef(0.3);

  useEffect(() => {
    let last = performance.now();
    const tick = (now) => {
      const dt = (now - last) / 1000;
      last = now;
      tRef.current += dt;
      const t = tRef.current;

      // base breath, slow 4s cycle
      const breath = 0.5 + 0.1 * Math.sin(t * 0.5 * Math.PI * 2 / 2);
      let target = breath;

      if (speaker === 'user') {
        // user voice: chunkier, more irregular
        const v = 0.5 + 0.35 * Math.sin(t * 6) * Math.sin(t * 2.3) + 0.15 * Math.sin(t * 11);
        target = Math.max(0.35, Math.min(1, Math.abs(v) + 0.15));
      } else if (speaker === 'agent') {
        // agent voice: smoother, cleaner cadence
        const v = 0.55 + 0.25 * Math.sin(t * 4.2) + 0.1 * Math.sin(t * 8.1);
        target = Math.max(0.4, Math.min(1, v));
      }

      targetRef.current = target;
      setAmp((prev) => prev + (target - prev) * 0.12);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [speaker]);

  return amp;
}

// VARIANT A: soft concentric breathing rings over a filled clay orb
function OrbVariantA({ speaker = 'idle', size = 440 }) {
  const amp = useAmplitude(speaker);
  const core = 0.42 + amp * 0.08;
  const ring1 = 0.55 + amp * 0.14;
  const ring2 = 0.72 + amp * 0.18;
  const ring3 = 0.88 + amp * 0.1;

  const userTint = speaker === 'user';
  const agentTint = speaker === 'agent';

  return (
    <div style={{ position: 'relative', width: size, height: size, display: 'grid', placeItems: 'center' }}>
      {/* outermost halo */}
      <div style={{
        position: 'absolute', width: size * ring3, height: size * ring3, borderRadius: '50%',
        background: `radial-gradient(circle, ${agentTint ? 'rgba(200, 116, 84, 0.12)' : 'rgba(217, 138, 99, 0.08)'} 0%, transparent 70%)`,
        transition: 'all 0.4s cubic-bezier(.4,0,.2,1)',
      }} />
      {/* ring 2 */}
      <div style={{
        position: 'absolute', width: size * ring2, height: size * ring2, borderRadius: '50%',
        border: '1px solid rgba(168, 84, 58, 0.18)',
        background: `radial-gradient(circle, rgba(217, 138, 99, 0.18) 0%, transparent 75%)`,
        transition: 'all 0.3s cubic-bezier(.4,0,.2,1)',
      }} />
      {/* ring 1 */}
      <div style={{
        position: 'absolute', width: size * ring1, height: size * ring1, borderRadius: '50%',
        background: `radial-gradient(circle, rgba(200, 116, 84, 0.32) 0%, rgba(200,116,84, 0.1) 80%, transparent 100%)`,
        transition: 'all 0.25s cubic-bezier(.4,0,.2,1)',
      }} />
      {/* core orb */}
      <div style={{
        position: 'absolute', width: size * core, height: size * core, borderRadius: '50%',
        background: `
          radial-gradient(circle at 35% 30%, #e79872 0%, #c87454 45%, #9c4a32 100%)
        `,
        boxShadow: `
          inset 0 -12px 40px rgba(90, 30, 10, 0.35),
          inset 0 12px 30px rgba(255, 220, 190, 0.25),
          0 20px 60px rgba(168, 84, 58, ${0.28 + amp * 0.15})
        `,
        transition: 'all 0.2s cubic-bezier(.4,0,.2,1)',
      }}>
        {/* highlight */}
        <div style={{
          position: 'absolute', top: '15%', left: '22%', width: '30%', height: '25%', borderRadius: '50%',
          background: 'radial-gradient(ellipse, rgba(255, 230, 200, 0.5) 0%, transparent 70%)',
          filter: 'blur(6px)',
        }} />
      </div>
      {/* speaker indicator dot */}
      {speaker !== 'idle' && (
        <div style={{
          position: 'absolute', bottom: -4, left: '50%', transform: 'translateX(-50%)',
          fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.2em',
          textTransform: 'uppercase', color: 'var(--muted)',
          opacity: 0.7,
        }}>
          {speaker === 'user' ? '· tú ·' : '· maría ·'}
        </div>
      )}
    </div>
  );
}

// VARIANT B: vertical waveform bars bending through the orb
function OrbVariantB({ speaker = 'idle', size = 440 }) {
  const amp = useAmplitude(speaker);
  const barCount = 48;
  const bars = Array.from({ length: barCount }, (_, i) => {
    const phase = i / barCount;
    const t = performance.now() / 1000;
    // signature wave shape — taller in middle
    const envelope = Math.sin(phase * Math.PI);
    const wiggle = 0.5 + 0.5 * Math.sin(phase * 22 + t * (speaker === 'idle' ? 1 : 4));
    const base = envelope * (0.25 + amp * 0.75);
    const h = base * (0.6 + wiggle * 0.4);
    return h;
  });

  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 50);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{ position: 'relative', width: size, height: size, display: 'grid', placeItems: 'center' }}>
      {/* background circle */}
      <div style={{
        position: 'absolute', width: size * 0.9, height: size * 0.9, borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(200, 116, 84, 0.08) 0%, transparent 70%)',
      }} />
      <div style={{
        position: 'absolute', width: size * 0.68, height: size * 0.68, borderRadius: '50%',
        border: '1px solid rgba(42, 33, 26, 0.1)',
      }} />
      {/* bars laid out horizontally, masked to circle */}
      <div style={{
        width: size * 0.76, height: size * 0.76,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 2,
        WebkitMaskImage: 'radial-gradient(circle, black 55%, transparent 70%)',
        maskImage: 'radial-gradient(circle, black 55%, transparent 70%)',
      }}>
        {bars.map((h, i) => {
          const max = size * 0.55;
          const bh = Math.max(3, h * max);
          return (
            <div key={i} style={{
              width: (size * 0.76 - barCount * 2) / barCount,
              height: bh,
              background: speaker === 'agent'
                ? 'linear-gradient(180deg, #c87454, #a8543a)'
                : speaker === 'user'
                ? 'linear-gradient(180deg, #d98a63, #c87454)'
                : 'linear-gradient(180deg, #b8a585, #8b7a5f)',
              borderRadius: 100,
              transition: 'height 0.08s linear, background 0.4s',
            }} />
          );
        })}
      </div>
      {/* center pulse */}
      <div style={{
        position: 'absolute', width: size * (0.08 + amp * 0.03), height: size * (0.08 + amp * 0.03),
        borderRadius: '50%', background: '#c87454',
        boxShadow: `0 0 ${20 + amp * 30}px rgba(200, 116, 84, 0.5)`,
        transition: 'all 0.15s',
      }} />
    </div>
  );
}

// VARIANT C: liquid metaball-style with animated gradient bloom
function OrbVariantC({ speaker = 'idle', size = 440 }) {
  const amp = useAmplitude(speaker);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let id = requestAnimationFrame(function loop() {
      setTick(performance.now() / 1000);
      id = requestAnimationFrame(loop);
    });
    return () => cancelAnimationFrame(id);
  }, []);

  const wobble = (seed) => 1 + 0.06 * Math.sin(tick * 1.5 + seed) + amp * 0.12 * Math.sin(tick * 3 + seed * 2);

  return (
    <div style={{ position: 'relative', width: size, height: size, display: 'grid', placeItems: 'center' }}>
      <svg width={size} height={size} viewBox="0 0 100 100" style={{ position: 'absolute', inset: 0 }}>
        <defs>
          <radialGradient id="orb-core" cx="40%" cy="35%">
            <stop offset="0%" stopColor="#f5c49e"/>
            <stop offset="40%" stopColor="#d98a63"/>
            <stop offset="80%" stopColor="#a8543a"/>
            <stop offset="100%" stopColor="#6a2f1e"/>
          </radialGradient>
          <radialGradient id="orb-halo" cx="50%" cy="50%">
            <stop offset="0%" stopColor="rgba(217, 138, 99, 0.4)"/>
            <stop offset="70%" stopColor="rgba(217, 138, 99, 0.06)"/>
            <stop offset="100%" stopColor="rgba(217, 138, 99, 0)"/>
          </radialGradient>
          <filter id="goo">
            <feGaussianBlur in="SourceGraphic" stdDeviation="1.2" />
            <feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -7"/>
          </filter>
        </defs>

        {/* outer halo */}
        <circle cx="50" cy="50" r={46 * wobble(0)} fill="url(#orb-halo)" />

        <g filter="url(#goo)">
          {/* main orb */}
          <circle cx="50" cy="50" r={22 * wobble(1)} fill="url(#orb-core)" />
          {/* satellites that appear when speaking */}
          {speaker !== 'idle' && [0, 1, 2, 3].map((i) => {
            const angle = tick * (0.6 + i * 0.2) + i * Math.PI / 2;
            const dist = 18 + 5 * Math.sin(tick * 2 + i) + amp * 4;
            const r = 4 + 2 * Math.sin(tick * 3 + i) + amp * 2;
            return (
              <circle key={i}
                cx={50 + Math.cos(angle) * dist}
                cy={50 + Math.sin(angle) * dist}
                r={r}
                fill="url(#orb-core)" />
            );
          })}
        </g>

        {/* rim */}
        <circle cx="50" cy="50" r={22 * wobble(1)} fill="none"
          stroke="rgba(255, 220, 190, 0.15)" strokeWidth="0.3"/>
      </svg>
    </div>
  );
}

function Orb({ variant = 'A', speaker = 'idle', size = 440 }) {
  if (variant === 'B') return <OrbVariantB speaker={speaker} size={size} />;
  if (variant === 'C') return <OrbVariantC speaker={speaker} size={size} />;
  return <OrbVariantA speaker={speaker} size={size} />;
}

Object.assign(window, { Orb, useAmplitude });
