/* Maketdagi ikonkalar (24x24, chiziqli) */
const P = {
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />,
  menu: <path d="M4 7h16M4 12h16M4 17h10" />,
  filter: <path d="M4 6h16M7 12h10M10 18h4" />,
  edit: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></>,
  up: <path d="M12 19V5M5 12l7-7 7 7" />,
  copy: <><rect x="9" y="9" width="11" height="11" rx="2.5" /><path d="M5 15V6a1 1 0 0 1 1-1h9" /></>,
  redo: <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  down: <path d="m6 9 6 6 6-6" />,
  ext: <path d="M7 17 17 7M9 7h8v8" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  scale: <path d="M12 3v18M7 21h10M5 7h14M5 7l-3 7a3 3 0 0 0 6 0Zm14 0-3 7a3 3 0 0 0 6 0Z" />,
  brief: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18" /></>,
  home: <><path d="M4 11 12 4l8 7v9H4Z" /><path d="M10 20v-5h4v5" /></>,
  users: <><circle cx="9" cy="8" r="3.2" /><path d="M3 20a6 6 0 0 1 12 0M16 4.5a3 3 0 0 1 0 6M21 20a5 5 0 0 0-3.5-4.8" /></>,
  car: <><path d="M5 16h14v-4l-2-5H7l-2 5Z" /><circle cx="8" cy="16.5" r="1.6" /><circle cx="16" cy="16.5" r="1.6" /></>,
  docq: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" /><path d="M14 3v5h5M10 12.5a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9v.4M12 18h.01" /></>,
  alert: <><path d="M12 4 2.5 20h19Z" /><path d="M12 10v4M12 17h.01" /></>,
  key: <><circle cx="8" cy="15" r="4" /><path d="m11 12 9-9M17 6l3 3M14 9l2 2" /></>,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" /><circle cx="12" cy="12" r="3" /></>,
  eyeoff: <><path d="M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-2.6 3.4M6.6 6.6C3.9 8.3 2.5 12 2.5 12S6 18.5 12 18.5c1.9 0 3.5-.6 4.9-1.5" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" /></>,
  spark: <path d="M12 3c.6 4.6 3.4 7.4 8 8-4.6.6-7.4 3.4-8 8-.6-4.6-3.4-7.4-8-8 4.6-.6 7.4-3.4 8-8Z" />,
  share: <><path d="M12 15V3.5M7.5 8 12 3.5 16.5 8" /><path d="M8 11H6.5A2.5 2.5 0 0 0 4 13.5v4A2.5 2.5 0 0 0 6.5 20h11a2.5 2.5 0 0 0 2.5-2.5v-4a2.5 2.5 0 0 0-2.5-2.5H16" /></>,
  plane: <path d="M21 4 3 11l6.5 2.5M21 4l-3.5 16-8-6.5M21 4 9.5 13.5V19l3-3" />,
  chat: <><path d="M4.5 19.5 5.6 16A8 8 0 1 1 8.4 18.6Z" /><path d="M9.5 9.5c.3 2 2 3.8 4.2 4.3l1-1.1 1.8.8" /></>,
  image: <><rect x="3.5" y="4.5" width="17" height="15" rx="3" /><circle cx="9" cy="10" r="1.7" /><path d="m20.5 16-4.5-4.5L6 19.5" /></>,
  shield: <><path d="M12 3 5 6v5.5c0 4.4 3 8 7 9.5 4-1.5 7-5.1 7-9.5V6Z" /><path d="m9 12 2.2 2.2L15.5 10" /></>,
  xray: <><path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2" /><path d="M7 12h10M9 8.5h6M9 15.5h6" /></>,
  chart: <><path d="M4 20h16" /><path d="M7 16v-5M12 16V6M17 16v-8" /></>,
  left: <path d="m15 6-6 6 6 6" />,
  table: <><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d="M3.5 9.5h17M3.5 14.5h17M9.5 9.5v10" /></>,
  bulb: <><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z" /></>,
};
export type IconName = keyof typeof P;

export function Icon({ name, className = "i" }: { name: IconName; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      {P[name]}
    </svg>
  );
}
