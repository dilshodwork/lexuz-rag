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
};
export type IconName = keyof typeof P;

export function Icon({ name, className = "i" }: { name: IconName; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      {P[name]}
    </svg>
  );
}
