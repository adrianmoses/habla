// Small shared primitives for the progress surfaces.
//
// Not a design system — just the handful of patterns Home already established
// (serif headings, mono eyebrow labels, hairline-bordered panels) pulled out so
// three screens don't each re-declare them inline.

import type { CSSProperties, ReactNode } from 'react';

export const page: CSSProperties = {
  flex: 1,
  padding: '20px 80px 80px',
  maxWidth: 1080,
  width: '100%',
};

export function PageTitle({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div style={{ marginBottom: 40 }}>
      <h1
        style={{
          fontFamily: 'var(--serif)',
          fontWeight: 400,
          fontSize: 56,
          lineHeight: 1.05,
          letterSpacing: '-0.02em',
          color: 'var(--ink)',
        }}
      >
        {title}
      </h1>
      {subtitle && (
        <p
          style={{
            fontFamily: 'var(--serif)',
            fontSize: 20,
            color: 'var(--ink-2)',
            marginTop: 12,
            maxWidth: 620,
          }}
        >
          {subtitle}
        </p>
      )}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontFamily: 'var(--mono)',
        fontSize: 11,
        letterSpacing: '0.2em',
        textTransform: 'uppercase',
        color: 'var(--muted)',
        marginBottom: 14,
      }}
    >
      {children}
    </div>
  );
}

export function Panel({
  children,
  style,
}: {
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        border: '1px solid var(--line)',
        borderRadius: 14,
        background: 'var(--cream)',
        padding: '22px 24px',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** Honest copy for a surface with no data yet — never a blank region. */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 14,
        color: 'var(--muted)',
        fontStyle: 'italic',
        padding: '8px 0',
      }}
    >
      {children}
    </div>
  );
}

/**
 * A failure confined to one surface (spec Key Decision: per-surface failure).
 * The rest of the page keeps rendering around it.
 */
export function ErrorNotice({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        padding: '12px 16px',
        borderRadius: 10,
        background: 'rgba(168, 84, 58, 0.08)',
        border: '1px solid rgba(168, 84, 58, 0.2)',
        color: 'var(--clay-deep)',
        fontSize: 13,
      }}
    >
      {children}
    </div>
  );
}

/** A 0–1 signal as a hairline meter. Label carries the meaning, not a number. */
export function Meter({ value, hint }: { value: number; hint: string }) {
  return (
    <div>
      <div
        style={{
          height: 6,
          borderRadius: 100,
          background: 'var(--cream-2)',
          border: '1px solid var(--line)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${value}%`,
            height: '100%',
            background: 'linear-gradient(90deg, #c87454, #d98a63)',
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
        {hint}
      </div>
    </div>
  );
}
