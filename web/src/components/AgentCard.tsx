// The agent identity card, extracted from Home so Ajustes can show it too.
//
// Presentational and static: the voice is configured server-side
// (`CARTESIA_VOICE_ID`), and no endpoint exposes it, so this describes the
// deployment's agent rather than reading it.

import { ChevronDownIcon } from './icons';

type Props = {
  /** Home shows the affordance chevron; Ajustes reads as settled config. */
  showChevron?: boolean;
};

export default function AgentCard({ showChevron = true }: Props) {
  return (
    <div
      style={{
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
      {showChevron && <ChevronDownIcon size={18} stroke="var(--muted)" />}
    </div>
  );
}
