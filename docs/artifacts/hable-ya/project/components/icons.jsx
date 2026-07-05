// Minimal line icons — 1.5px stroke, 20x20 viewbox
const Icon = ({ children, size = 20, stroke = 'currentColor', strokeWidth = 1.5, style }) => (
  <svg width={size} height={size} viewBox="0 0 20 20" fill="none"
    stroke={stroke} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
    style={style}>
    {children}
  </svg>
);

const MicIcon = (p) => <Icon {...p}>
  <rect x="7" y="2" width="6" height="10" rx="3"/>
  <path d="M4 9a6 6 0 0 0 12 0M10 15v3M7 18h6"/>
</Icon>;

const PauseIcon = (p) => <Icon {...p}>
  <rect x="6" y="4" width="3" height="12" rx="0.5"/>
  <rect x="11" y="4" width="3" height="12" rx="0.5"/>
</Icon>;

const PlayIcon = (p) => <Icon {...p}>
  <path d="M6 4l10 6-10 6V4z" fill="currentColor"/>
</Icon>;

const CloseIcon = (p) => <Icon {...p}>
  <path d="M5 5l10 10M15 5L5 15"/>
</Icon>;

const ArrowRightIcon = (p) => <Icon {...p}>
  <path d="M4 10h12M12 6l4 4-4 4"/>
</Icon>;

const ArrowLeftIcon = (p) => <Icon {...p}>
  <path d="M16 10H4M8 6l-4 4 4 4"/>
</Icon>;

const CheckIcon = (p) => <Icon {...p}>
  <path d="M4 10l4 4 8-8"/>
</Icon>;

const SparkIcon = (p) => <Icon {...p}>
  <path d="M10 2v4M10 14v4M2 10h4M14 10h4M4.5 4.5l2.5 2.5M13 13l2.5 2.5M4.5 15.5l2.5-2.5M13 7l2.5-2.5"/>
</Icon>;

const WaveIcon = (p) => <Icon {...p}>
  <path d="M2 10h1M5 6v8M8 3v14M11 6v8M14 3v14M17 6v8"/>
</Icon>;

const HeadphonesIcon = (p) => <Icon {...p}>
  <path d="M3 12v-2a7 7 0 0 1 14 0v2M3 12v3a2 2 0 0 0 2 2h1v-5H4M17 12v3a2 2 0 0 1-2 2h-1v-5h2"/>
</Icon>;

const BookIcon = (p) => <Icon {...p}>
  <path d="M3 4a2 2 0 0 1 2-2h10v14H5a2 2 0 0 0-2 2V4zM3 18a2 2 0 0 1 2-2h10"/>
</Icon>;

const UserIcon = (p) => <Icon {...p}>
  <circle cx="10" cy="7" r="3.5"/>
  <path d="M3.5 17c.8-3.2 3.4-5 6.5-5s5.7 1.8 6.5 5"/>
</Icon>;

const FlameIcon = (p) => <Icon {...p}>
  <path d="M10 18c-3.3 0-6-2.4-6-5.5 0-2 1-3 2-4 .5 1 1.5 1.5 2 1 0-2 0-5 2-7 0 2 1 3 2 4 2 2 4 3.5 4 6 0 3.1-2.7 5.5-6 5.5z"/>
</Icon>;

const CalendarIcon = (p) => <Icon {...p}>
  <rect x="3" y="4" width="14" height="13" rx="1.5"/>
  <path d="M3 8h14M7 2v4M13 2v4"/>
</Icon>;

const QuoteIcon = (p) => <Icon {...p}>
  <path d="M5 8c0-1.5 1-3 3-3M5 8v4h3V8H5zM12 8c0-1.5 1-3 3-3M12 8v4h3V8h-3z"/>
</Icon>;

const ChevronDownIcon = (p) => <Icon {...p}>
  <path d="M5 8l5 5 5-5"/>
</Icon>;

const DotIcon = ({ size = 8, color = 'currentColor' }) => (
  <span style={{ display: 'inline-block', width: size, height: size, borderRadius: '50%', background: color }} />
);

Object.assign(window, {
  Icon, MicIcon, PauseIcon, PlayIcon, CloseIcon, ArrowRightIcon, ArrowLeftIcon,
  CheckIcon, SparkIcon, WaveIcon, HeadphonesIcon, BookIcon, UserIcon,
  FlameIcon, CalendarIcon, QuoteIcon, ChevronDownIcon, DotIcon,
});
