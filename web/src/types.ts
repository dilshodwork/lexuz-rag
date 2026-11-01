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

export type TrustClaim = { start: number; end: number; ok: boolean; cites: number[]; reasons: string[]; lex?: number | null; cos?: number };
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
  xray?: XRay;      // RAG ichi (yuridik javob uchun)
};

// ---------------------------------------------------------------- X-ray (serverdagi rag.XRay)
export type XrItem = {
  chunk_id: string; rank: number; n?: number; cosine?: number | null; score?: number | null;
  rank_dense?: number | null; rank_bm25?: number | null; via?: "dense" | "bm25" | "both";
};
export type XrSearch = {
  query: string; q_dense: string; q_bm25: string; bm25_tokens: string[]; mode: string; lang: string | null;
  params: { w_dense: number; w_bm25: number; w_bm25_default: number; rrf_k: number; n_each: number; k: number };
  filters: { only_active: boolean; no_amending: boolean; doc_types: string[] | null };
  counts: { dense: number; bm25: number; fused: number };
  dense: XrItem[]; bm25: XrItem[]; fused: XrItem[]; ms: number;
};
export type XrSpan = { key: string; label: string; start: number; ms: number; search?: number };
export type XrLabel = { doc: string; art: string; title: string; status: string; type: string };
export type XrLLM = { via: "server" | "own"; provider: string | null; model: string | null; start?: number | null; first_token?: number | null; end?: number | null };
export type XRay = {
  question: string; mode: Mode;
  analysis: { lang: AnswerLang; lang_name: string; detected: AnswerLang; forced: boolean; script: "lotin" | "kirill"; latin: string; parts: string[]; planner: string | null; reuse?: boolean };
  searches: XrSearch[];
  fusion: { method: string; rrf_k: number; before: number; after: number; from: Record<string, number[]> } | null;
  labels: Record<string, XrLabel>;
  final: XrItem[];
  threshold: { no_answer_cos: number; best_cos: number | null; no_answer: boolean };
  prompt: { system?: string; user?: string; tokens: { system: number; user: number; total: number; method: string }; chars: number } | null;
  timeline: XrSpan[]; total_ms: number;
  llm?: XrLLM;
  refetched?: boolean; // X-ray o'chiq edi: qidiruv keyin (LLM'siz) qayta bajarildi
};

// ---------------------------------------------------------------- baholash (eval/results.json)
export type EvalMode = "dense" | "bm25" | "hybrid" | "hybrid_plan";
export type EvalSummary = Record<string, number> & { recall_curve: number[]; n: number; avg_ms: number; p50_ms: number; p95_ms: number };
export type EvalReject = { threshold: number; n_none: number; correct_reject: number; n_answerable: number; false_reject: number; reject_rate: number; false_reject_rate: number; accuracy: number; balanced_accuracy: number };
export type EvalTop = { rank: number; chunk_id: string; doc: string; art: string; title: string; gold: boolean; cos: number | null; rank_dense: number | null; rank_bm25: number | null };
export type EvalQ = {
  id: string; question: string; category: string; difficulty: string; lang: AnswerLang; script: string; answerable: boolean;
  split?: EvalSplit; lang_detected?: AnswerLang;
  gold: { doc_id: string; article: string; doc: string }[]; parts: string[];
  gold_rank_dense: number | null; gold_rank_bm25: number | null;
  modes: Record<EvalMode, { ms: number; best_cos: number | null; top: EvalTop[]; metrics?: Record<string, number> & { rank: number | null } }>;
};
export type EvalSlice = Record<string, Record<EvalMode, { n: number; "recall@5": number; "mrr@10": number; "hit@1": number }>>;
export type EvalResults = {
  meta: { created: string; commit: string | null; dirty: boolean | null; n_questions: number; n_answerable: number; n_none: number; k: number; modes: EvalMode[];
    mode_names: Record<EvalMode, string>; params: Record<string, unknown> & { W_BM25: number; NO_ANSWER_COS: number; W_DENSE: number; RRF_K: number; N_EACH: number; K_CONTEXT: number };
    counts: Record<string, Record<string, number>>; elapsed_s: number | null };
  summary: Record<EvalMode, EvalSummary>;
  rejection: Record<EvalMode, EvalReject | null>;
  slices: Record<"category" | "lang" | "difficulty", EvalSlice>;
  by_split?: Partial<Record<EvalSplit, EvalBlock>>;
  questions: EvalQ[];
};
export type EvalSplit = "dev" | "test";
/** Bitta qism (dev / test) yoki butun to'plam bo'yicha jamlanma */
export type EvalBlock = {
  n_questions: number; n_answerable: number; n_none: number; counts?: Record<string, Record<string, number>>;
  summary: Record<EvalMode, EvalSummary>; rejection: Record<EvalMode, EvalReject | null>;
  slices: Record<"category" | "lang" | "difficulty", EvalSlice>;
};
type WRow = { w_bm25: number } & Record<string, number>;
export type EvalSweep = {
  selected_on?: string;
  w_bm25: { current: number; grid: WRow[]; grid_by_split?: Record<string, WRow[]>; best: WRow; note: string };
  no_answer_cos: { current: number; grid: EvalReject[]; grid_by_split?: Record<string, EvalReject[]>; best: EvalReject; answerable_cos: { min: number; p10: number; median: number }; none_cos: number[]; separable: boolean };
  meta?: { created: string; commit: string | null };
};
export type EvalBaselineV2 = { meta: { created: string; commit: string | null; n_questions: number }; by_split: Record<EvalSplit, EvalBlock>; ranks: Record<string, number | null> };
type Lv = { high: number; medium: number; low: number };
export type EvalTrustCal = {
  params: { old: { ok: number }; new: { ok: number; num: number; ctx: boolean } };
  ru_true: { before: [number, number]; after: [number, number] }; ru_false: { before: [number, number]; after: [number, number] };
  uz_false: [number, number]; levels: Record<"ru_real" | "uz_real", { before: Lv; after: Lv }>;
};
export type EvalAnswers = {
  meta: { created: string; commit: string; provider: string; model: string; llm_requests: number; stopped: string | null };
  summary: { n: number; answered: number; faithfulness: number | null; trust_high: number; cites_valid: number; gold_cited: number };
  items: { id: string; question: string; status: string; note?: string; trust?: { level: string; checked: number; supported: number }; faithfulness?: number | null; cited?: number[]; cites_valid?: boolean; gold_cited?: boolean; total_s?: number }[];
};
export type EvalRun = { running: boolean; done: number; total: number; current: string; error: string | null; started: number | null; finished: number | null };
export type EvalData = { results: EvalResults | null; sweep: EvalSweep | null; baseline: Pick<EvalResults, "meta" | "summary" | "rejection"> | null; answers: EvalAnswers | null;
  baseline_v2?: EvalBaselineV2 | null; trust_cal?: EvalTrustCal | null; run: EvalRun; protected: boolean };

export type Conv = { id: string; title: string; created: number; updated: number; turns: Turn[] };

export type Filters = { only_active: boolean; include_amending: boolean; doc_types: string[] };

/** Bepul sinov (server kaliti): free=false bo'lsa serverda bepul AI yo'q */
export type Quota = { free: boolean; limit: number; used: number; left: number; reason: "user" | "global" | null };

export type Stats ={ documents: number | null; chunks: number | null; base_date: string | null };

export const DOC_TYPES = ["Qonun", "Kodeks", "Konstitutsiya"] as const;
export const DEFAULT_FILTERS: Filters = { only_active: true, include_amending: false, doc_types: [...DOC_TYPES] };
