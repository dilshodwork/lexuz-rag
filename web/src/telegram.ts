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
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  onEvent(e: string, cb: () => void): void;
  BackButton?: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: { impactOccurred(s: "light" | "medium" | "soft"): void; selectionChanged(): void };
  openLink?: (url: string) => void;
  openTelegramLink?: (url: string) => void;
  CloudStorage?: {
    setItem(k: string, v: string, cb?: (err: string | null, ok?: boolean) => void): void;
    getItem(k: string, cb: (err: string | null, v?: string) => void): void;
    removeItem(k: string, cb?: (err: string | null, ok?: boolean) => void): void;
  };
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

/** Javob yozilayotganda Mini App'ni tasodifan yopib yubormaslik uchun Telegram "yopilsinmi?" deb so'raydi (6.2+) */
export function setClosingConfirm(on: boolean) {
  if (!inTelegram || !tg?.isVersionAtLeast?.("6.2")) return;
  try {
    if (on) tg.enableClosingConfirmation?.(); else tg.disableClosingConfirmation?.();
  } catch { /* eski Telegram */ }
}

export function haptic() {
  if (inTelegram) tg?.HapticFeedback?.impactOccurred("light");
}

/** Server Mini App foydalanuvchisini aniqlashi uchun (imzoni server TELEGRAM_BOT_TOKEN bilan tekshiradi) */
export const telegramInitData = () => (inTelegram ? tg!.initData : "");

/** Telegram bulutli xotirasi (foydalanuvchi + bot bo'yicha, Bot API 6.9+). Oddiy brauzerda null. */
export function cloudStorage() {
  if (!inTelegram || !tg?.CloudStorage || !tg.isVersionAtLeast?.("6.9")) return null;
  const cs = tg.CloudStorage;
  return {
    get: (k: string) => new Promise<string | null>((res) => {
      try { cs.getItem(k, (err, v) => res(err ? null : v || "")); } catch { res(null); }
    }),
    set: (k: string, v: string) => { try { cs.setItem(k, v); } catch { /* eski Telegram */ } },
    remove: (k: string) => { try { cs.removeItem(k); } catch { /* eski Telegram */ } },
  };
}

/** Ulashish havolalari: t.me - Telegram ichida openTelegramLink (Mini App yopilmaydi), boshqasi - tizim brauzerida */
export function openShareLink(url: string) {
  if (inTelegram && tg) {
    if (url.startsWith("https://t.me/") && tg.openTelegramLink) tg.openTelegramLink(url);
    else if (tg.openLink) tg.openLink(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

/** Tashqi havola: Telegram ichida tizim brauzerida ochiladi (oddiy brauzerda <a target=_blank>) */
export function openExternal(url: string, e?: { preventDefault(): void }) {
  if (inTelegram && tg?.openLink) {
    e?.preventDefault();
    tg.openLink(url);
  }
}
