// Shared page chrome: logo, nav, avatar, and the scroll container.
//
// Extracted from Home's header so the four screens share one navigation and it
// cannot drift. `#root` is `height:100vh; overflow:hidden` (globals.css), so
// every screen owns its own scroll — this is where that lives.

import type { CSSProperties, ReactNode } from 'react';
import { navigate, type Route } from '../lib/router';

const NAV: readonly { route: Route; label: string }[] = [
  { route: 'progreso', label: 'Progreso' },
  { route: 'historial', label: 'Historial' },
  { route: 'ajustes', label: 'Ajustes' },
];

function navLinkStyle(active: boolean): CSSProperties {
  return {
    fontSize: 13,
    color: active ? 'var(--ink)' : 'var(--ink-2)',
    cursor: 'pointer',
    textDecoration: 'none',
    paddingBottom: 2,
    borderBottom: active
      ? '1px solid var(--clay)'
      : '1px solid transparent',
    transition: 'color 0.15s, border-color 0.15s',
  };
}

type Props = {
  current: Route;
  children: ReactNode;
};

export default function AppShell({ current, children }: Props) {
  return (
    <div
      style={{
        height: '100vh',
        width: '100vw',
        overflow: 'auto',
        background: 'var(--cream)',
        display: 'flex',
        flexDirection: 'column',
      }}
      className="no-scrollbar"
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '28px 48px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            cursor: 'pointer',
          }}
          onClick={() => navigate('home')}
        >
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background:
                'radial-gradient(circle at 35% 30%, #e79872 0%, #c87454 60%, #9c4a32 100%)',
              boxShadow: 'inset 0 -4px 8px rgba(90, 30, 10, 0.3)',
            }}
          />
          <span
            style={{
              fontFamily: 'var(--serif)',
              fontSize: 22,
              letterSpacing: '-0.01em',
            }}
          >
            hable ya
          </span>
        </div>
        <nav style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
          {NAV.map(({ route, label }) => (
            <a
              key={route}
              onClick={() => navigate(route)}
              style={navLinkStyle(current === route)}
            >
              {label}
            </a>
          ))}
          {/* The initial is still a placeholder — the learner has no name until
              spec #021 gives the profile one. It navigates, so at least it is
              no longer a decorative cursor:pointer. */}
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: '50%',
              background: 'var(--sand)',
              border: '1px solid var(--line)',
              display: 'grid',
              placeItems: 'center',
              fontFamily: 'var(--serif)',
              fontSize: 15,
              color: 'var(--ink-2)',
              cursor: 'pointer',
            }}
            onClick={() => navigate('ajustes')}
            title="Ajustes"
          >
            A
          </div>
        </nav>
      </header>
      {children}
    </div>
  );
}
