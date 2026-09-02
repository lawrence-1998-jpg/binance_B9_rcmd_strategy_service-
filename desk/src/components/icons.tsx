type P = { className?: string }
/** 默认 20×20；父级规则（.tab svg / .cap svg / .empty svg）更具体，会盖掉它 */
const base = {
  className: 'icon',
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export const IcToday = (p: P) => (
  <svg {...base} {...p}><path d="M3 10.5 12 3.5l9 7" /><path d="M5.5 9.5V20.5h13V9.5" /></svg>
)
export const IcWork = (p: P) => (
  <svg {...base} {...p}><path d="M12 3 21 8l-9 5-9-5 9-5Z" /><path d="M3 16l9 5 9-5" /></svg>
)
export const IcLife = (p: P) => (
  <svg {...base} {...p}><path d="M12 20s-7-4.4-7-9.2A3.9 3.9 0 0 1 12 8a3.9 3.9 0 0 1 7 2.8C19 15.6 12 20 12 20Z" /></svg>
)
export const IcReview = (p: P) => (
  <svg {...base} {...p}><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z" /></svg>
)
export const IcPlus = (p: P) => (
  <svg {...base} strokeWidth={2.1} {...p}><path d="M12 5.5v13M5.5 12h13" /></svg>
)
export const IcClose = (p: P) => (
  <svg {...base} strokeWidth={2} {...p}><path d="M6 6l12 12M18 6 6 18" /></svg>
)
export const IcBack = (p: P) => (
  <svg {...base} strokeWidth={2.2} {...p}><path d="M15 5l-7 7 7 7" /></svg>
)
export const IcGear = (p: P) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="3.2" />
    <path d="M19.4 14a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z" />
  </svg>
)
export const IcNote = (p: P) => (
  <svg {...base} strokeWidth={1.3} {...p}>
    <path d="M4 5.5h11l5 5V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19Z" />
    <path d="M14.5 5.5v5.5H20" /><path d="M8 14.5h7" />
  </svg>
)
export const IcTrip = (p: P) => (
  <svg {...base} strokeWidth={1.3} {...p}>
    <path d="M3.5 14.5 21 9l-1 3.5-11.5 4L7 20l-1.5-.5-.5-3.5-1.5-1.5Z" />
  </svg>
)
export const IcTrash = (p: P) => (
  <svg {...base} {...p}><path d="M4.5 6.5h15M9.5 6.5V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v1.5M7 6.5l.8 12a1.5 1.5 0 0 0 1.5 1.4h5.4a1.5 1.5 0 0 0 1.5-1.4l.8-12" /></svg>
)
export const IcWand = (p: P) => (
  <svg {...base} {...p}>
    <path d="M4 20 15 9" /><path d="M13.5 4.5 14.5 7l2.5 1-2.5 1-1 2.5-1-2.5L10 8l2.5-1Z" />
    <path d="M19 13.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6Z" />
  </svg>
)
export const IcCopy = (p: P) => (
  <svg {...base} {...p}>
    <rect x="9" y="9" width="11" height="11" rx="2.5" />
    <path d="M5.5 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v.5" />
  </svg>
)
export const IcMore = (p: P) => (
  <svg {...base} strokeWidth={2.6} strokeLinecap="round" {...p}>
    <path d="M6 12h.01M12 12h.01M18 12h.01" />
  </svg>
)
export const IcCheck = (p: P) => (
  <svg {...base} strokeWidth={2.2} {...p}><path d="M4.5 12.5 9.5 17.5 19.5 6.5" /></svg>
)
