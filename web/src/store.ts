import { DEFAULT_FILTERS, DOC_TYPES, type Conv, type Filters, type LangPref } from "./types";

const K = { convs: "dalil.convs.v1", filters: "dalil.filters.v1", theme: "dalil.theme", lang: "dalil.lang" };
const MAX_CONVS = 60;

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* xotira to'lgan yoki taqiqlangan (maxfiy rejim) - tarix saqlanmaydi */
  }
}

export function loadConvs(): Conv[] {
  const list = read<Conv[]>(K.convs, []);
  // sahifa oqim o'rtasida yopilgan bo'lsa - "to'xtatildi"
  const live = (s: string) => s === "searching" || s === "writing";
  for (const c of list) {
    for (const t of c.turns) {
      if (live(t.status)) t.status = "stopped";
      if (t.simple && live(t.simple.status)) t.simple.status = "stopped";
      if (t.trust === "pending") t.trust = undefined;
      if (t.simple?.trust === "pending") t.simple.trust = undefined;
    }
  }
  return list;
}

export function saveConvs(list: Conv[]) {
  let l = list.slice(0, MAX_CONVS);
  write(K.convs, l);
  // sig'masa eskilarini tashlab yana urinish
  while (l.length > 1 && localStorage.getItem(K.convs) === null) {
    l = l.slice(0, Math.floor(l.length / 2));
    write(K.convs, l);
  }
}

export function loadFilters(): Filters {
  const f = read<Filters>(K.filters, DEFAULT_FILTERS);
  const types = (f.doc_types || []).filter((t) => (DOC_TYPES as readonly string[]).includes(t));
  return { only_active: f.only_active !== false, include_amending: !!f.include_amending, doc_types: types.length ? types : [...DOC_TYPES] };
}
export const saveFilters = (f: Filters) => write(K.filters, f);

export const LANG_PREFS: { v: LangPref; label: string; short: string }[] = [
  { v: "auto", label: "Avto", short: "" }, { v: "uz", label: "Oʻzbekcha", short: "Oʻzb" },
  { v: "uz_cyr", label: "Ўзбекча", short: "Ўзб" }, { v: "ru", label: "Русский", short: "Рус" },
];
export const loadLang = (): LangPref => {
  const v = read<LangPref>(K.lang, "auto");
  return LANG_PREFS.some((x) => x.v === v) ? v : "auto";
};
export const saveLang = (v: LangPref) => write(K.lang, v);

export const loadTheme = () => read<"light" | "dark" | null>(K.theme, null);
export const saveTheme = (t: "light" | "dark") => write(K.theme, t);

export const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

export function dayGroup(ts: number): string {
  const d = new Date(ts), now = new Date();
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff <= 0) return "Bugun";
  if (diff === 1) return "Kecha";
  if (diff < 7) return "Shu hafta";
  return "Oldinroq";
}

export function timeLabel(ts: number): string {
  const d = new Date(ts);
  const g = dayGroup(ts);
  if (g === "Bugun") return d.toLocaleTimeString("uz-UZ", { hour: "2-digit", minute: "2-digit", hour12: false });
  if (g === "Kecha") return "Kecha";
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function filtersLabel(f: Filters, lang: LangPref = "auto") {
  const l = LANG_PREFS.find((x) => x.v === lang)?.short;
  return `${f.only_active ? "Amaldagi" : "Barchasi"} · ${f.doc_types.length} tur${f.include_amending ? " · +oʻzg." : ""}${l ? ` · ${l}` : ""}`;
}

export const isDefaultFilters = (f: Filters) =>
  f.only_active && !f.include_amending && f.doc_types.length === DOC_TYPES.length;
