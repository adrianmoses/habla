import type { Speaker } from '../../voice/types';

type Props = {
  speaker: Speaker;
  amp: number;
  size?: number;
};

export default function OrbHalo({ speaker, amp, size = 440 }: Props) {
  const core = 0.42 + amp * 0.08;
  const ring1 = 0.55 + amp * 0.14;
  const ring2 = 0.72 + amp * 0.18;
  const ring3 = 0.88 + amp * 0.1;

  const agentTint = speaker === 'agent';

  return (
    <div
      style={{
        position: 'relative',
        width: size,
        height: size,
        display: 'grid',
        placeItems: 'center',
      }}
    >
      <div
        style={{
          position: 'absolute',
          width: size * ring3,
          height: size * ring3,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${
            agentTint ? 'rgba(200, 116, 84, 0.12)' : 'rgba(217, 138, 99, 0.08)'
          } 0%, transparent 70%)`,
          transition: 'all 0.4s cubic-bezier(.4,0,.2,1)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: size * ring2,
          height: size * ring2,
          borderRadius: '50%',
          border: '1px solid rgba(168, 84, 58, 0.18)',
          background:
            'radial-gradient(circle, rgba(217, 138, 99, 0.18) 0%, transparent 75%)',
          transition: 'all 0.3s cubic-bezier(.4,0,.2,1)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: size * ring1,
          height: size * ring1,
          borderRadius: '50%',
          background:
            'radial-gradient(circle, rgba(200, 116, 84, 0.32) 0%, rgba(200,116,84, 0.1) 80%, transparent 100%)',
          transition: 'all 0.25s cubic-bezier(.4,0,.2,1)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: size * core,
          height: size * core,
          borderRadius: '50%',
          background:
            'radial-gradient(circle at 35% 30%, #e79872 0%, #c87454 45%, #9c4a32 100%)',
          boxShadow: `
            inset 0 -12px 40px rgba(90, 30, 10, 0.35),
            inset 0 12px 30px rgba(255, 220, 190, 0.25),
            0 20px 60px rgba(168, 84, 58, ${0.28 + amp * 0.15})
          `,
          transition: 'all 0.2s cubic-bezier(.4,0,.2,1)',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: '15%',
            left: '22%',
            width: '30%',
            height: '25%',
            borderRadius: '50%',
            background:
              'radial-gradient(ellipse, rgba(255, 230, 200, 0.5) 0%, transparent 70%)',
            filter: 'blur(6px)',
          }}
        />
      </div>
      {speaker !== 'idle' && (
        <div
          style={{
            position: 'absolute',
            bottom: -4,
            left: '50%',
            transform: 'translateX(-50%)',
            fontFamily: 'var(--mono)',
            fontSize: 10,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--muted)',
            opacity: 0.7,
          }}
        >
          {speaker === 'user' ? '· tú ·' : '· maría ·'}
        </div>
      )}
    </div>
  );
}
