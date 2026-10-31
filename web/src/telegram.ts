/* Telegram Mini App integratsiyasi. Oddiy brauzerda hech narsa qilmaydi.
   https://core.telegram.org/bots/webapps */

type Inset = { top?: number; bottom?: number; left?: number; right?: number };
type TgWebApp = {
  initData: string;
  colorScheme: "light" | "dark";
  viewportStableHeight: number;
  safeAreaInset?: Inset;
  contentSafeAreaInset?: Inset;
  ready(): void;
  expand(): void;
  disableVerticalSwipes?: () => void;
  setHeaderColor?: (c: string) => void;
  setBackgroundColor?: (c: string) => void;
  setBottomBarColor?: (c: string) => void;
  isVersionAtLeast?: (v: string) => boolean;
  onEvent(e: string, cb: () => void): void;
  BackButton?: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: { impactOccurred(s: "light" | "medium" | "soft"): void; selectionChanged(): void };
};

const tg: TgWebApp | undefined = (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp;
/** initData bo'sh bo'lmasa - haqiqatan Telegram ichida ochilgan */
export const inTelegram = !!tg && !!tg.initData;

export function telegramScheme(): "light" | "dark" | null {
  return inTelegram ? tg!.colorScheme : null;
}

export function initTelegram(onScheme: (s: "light" | "dark") => void) {
  if (!inTelegram || !tg) return;
  const root = document.documentElement;
  root.classList.add("tg");
  tg.ready();
  tg.expand();
  tg.disableVerticalSwipes?.(); // pastga sudrash varaqlarni yopsin, ilovani emas
  const vh = () => root.style.setProperty("--app-h", `${tg.viewportStableHeight || window.innerHeight}px`);
  const safe = () => {
    const a = tg.safeAreaInset || {}, c = tg.contentSafeAreaInset || {};
    root.style.setProperty("--tg-st", `${(a.top || 0) + (c.top || 0)}px`);
    root.style.setProperty("--tg-sb", `${(a.bottom || 0) + (c.bottom || 0)}px`);
  };
  vh();
  safe();
  tg.onEvent("viewportChanged", vh);
  tg.onEvent("safeAreaChanged", safe);
  tg.onEvent("contentSafeAreaChanged", safe);
  tg.onEvent("themeChanged", () => onScheme(tg.colorScheme));
}

/** Telegram sarlavha va fon rangini ilova temasiga moslash */
export function setTelegramChrome(bg: string) {
  if (!inTelegram || !tg) return;
  try {
    tg.setHeaderColor?.(bg);
    tg.setBackgroundColor?.(bg);
    tg.setBottomBarColor?.(bg);
  } catch {
    /* eski Telegram versiyasi */
  }
}

let backCb: (() => void) | null = null;
/** Chat ochiq bo'lsa Telegram'ning "orqaga" tugmasi bosh sahifaga qaytaradi */
export function setBackButton(cb: (() => void) | null) {
  const b = inTelegram ? tg?.BackButton : undefined;
  if (!b) return;
  if (backCb) b.offClick(backCb);
  backCb = cb;
  if (cb) { b.onClick(cb); b.show(); } else b.hide();
}

export function haptic() {
  if (inTelegram) tg?.HapticFeedback?.impactOccurred("light");
}
