export type Source = {
  n: number;
  chunk_id: string;
  doc_title: string;
  doc_type: string;
  doc_number: string | null;
  article_number: string | null;
  article_title: string | null;
  chapter: string | null;
  section: string | null;
  status: string;
  last_edition_date: string | null;
  source_url: string;
  doc_url: string | null;
  heading: string | null;
  text: string;
  cosine: number | null;
  score: number | null;
};

export type TurnStatus = "searching" | "writing" | "done" | "notfound" | "error" | "stopped";

/** Ekranda ko'rinadigan qidiruv bosqichi (serverdagi rag.prepare_steps; "write" - brauzer o'zi qo'shadi) */
export type Step = { key: string; label: string; state: "run" | "done"; detail?: string; ms?: number };

export type TrustClaim = { start: number; end: number; ok: boolean; cites: number[]; reasons: string[] };
/** /api/verify natijasi. level=null - tekshiriladigan da'vo yo'q */
export type Trust = { level: "high" | "medium" | "low" | null; checked: number; supported: number; claims: TrustClaim[] };

/** Javob tili: savoldan avtomatik yoki majburan */
export type AnswerLang = "uz" | "uz_cyr" | "ru";
export type LangPref = "auto" | AnswerLang;
export type Mode = "legal" | "simple";

/** Bitta javob varianti (yuridik yoki sodda) */
export type Variant = {
  text: string;
  status: TurnStatus;
  model?: string | null;
  error?: { code: string; message: string };
  ms?: number;
  noLLM?: boolean; // qidiruv hech narsa topmadi, LLM chaqirilmadi
  steps?: Step[];
  followups?: string[];
  trust?: Trust | "pending" | "error";
};

export type Turn = Variant & {
  id: string;
  q: string;
  sources: Source[];
  at: number;
  lang?: AnswerLang;
  parts?: string[];
  simple?: Variant; // "Sodda qilib tushuntir" (o'sha manbalar bilan)
  view?: Mode;
};

export type Conv = { id: string; title: string; created: number; updated: number; turns: Turn[] };

export type Filters = { only_active: boolean; include_amending: boolean; doc_types: string[] };

/** Bepul sinov (server kaliti): free=false bo'lsa serverda bepul AI yo'q */
export type Quota = { free: boolean; limit: number; used: number; left: number; reason: "user" | "global" | null };

export type Stats ={ documents: number | null; chunks: number | null; base_date: string | null };

export const DOC_TYPES = ["Qonun", "Kodeks", "Konstitutsiya"] as const;
export const DEFAULT_FILTERS: Filters = { only_active: true, include_amending: false, doc_types: [...DOC_TYPES] };
