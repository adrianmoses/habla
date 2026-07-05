import type { CSSProperties, ReactNode } from 'react';

type IconProps = {
  size?: number;
  stroke?: string;
  strokeWidth?: number;
  style?: CSSProperties;
};

type WrapperProps = IconProps & { children: ReactNode };

const Icon = ({
  children,
  size = 20,
  stroke = 'currentColor',
  strokeWidth = 1.5,
  style,
}: WrapperProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 20 20"
    fill="none"
    stroke={stroke}
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    style={style}
  >
    {children}
  </svg>
);

export const MicIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="7" y="2" width="6" height="10" rx="3" />
    <path d="M4 9a6 6 0 0 0 12 0M10 15v3M7 18h6" />
  </Icon>
);

export const PauseIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="6" y="4" width="3" height="12" rx="0.5" />
    <rect x="11" y="4" width="3" height="12" rx="0.5" />
  </Icon>
);

export const PlayIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M6 4l10 6-10 6V4z" fill="currentColor" />
  </Icon>
);

export const CloseIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 5l10 10M15 5L5 15" />
  </Icon>
);

export const ArrowRightIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 10h12M12 6l4 4-4 4" />
  </Icon>
);

export const SparkIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10 2v4M10 14v4M2 10h4M14 10h4M4.5 4.5l2.5 2.5M13 13l2.5 2.5M4.5 15.5l2.5-2.5M13 7l2.5-2.5" />
  </Icon>
);

export const ChevronDownIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 8l5 5 5-5" />
  </Icon>
);

export const DotIcon = ({
  size = 8,
  color = 'currentColor',
}: {
  size?: number;
  color?: string;
}) => (
  <span
    style={{
      display: 'inline-block',
      width: size,
      height: size,
      borderRadius: '50%',
      background: color,
    }}
  />
);
