import { AiError, streamAi, type AiConfig } from "./ai";
import { uid } from "./store";
import { telegramInitData } from "./telegram";
import { AnswerStream, type PostRules } from "./textproc";
import type { AnswerLang, Filters, LangPref, Mode, Quota, Source, Stats, Step, Trust } from "./types";

export type AskHandlers = {
  onStep: (s: Step) => void;
  onSources: (d: { sources: Source[]; no_answer: boolean; lang?: AnswerLang; parts?: string[] }) => void;
  onDelta: (text: string) => void;
  onFollowups: (items: string[]) => void;
  onDone: (d: { no_answer: boolean; model: string | null; ms: number }) => void;
  onError: (d: { code: string; message: string }) => void;
  onQuota?: (q: Quota) => void;
};

/** Savol parametrlari. Promptni server yig'adi, brauzer faqat shularni yuboradi. */
export type AskParams = {
  question: string;
  filters: Filters;
  lang: LangPref;
  mode?: Mode;
  chunk_ids?: string[];   // sodda rejim: o'sha manbalar, qayta qidiruvsiz
  base_answer?: string;   // sodda rejim: yuridik javob matni
};

/** Bepul limit uchun foydalanuvchi: qurilma ID (shu brauzerda doimiy) va Telegram initData */
function who(): Record<string, string> {
  let id = "";
  try {
    id = localStorage.getItem("dalil.did") || "";
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
      id = (crypto.randomUUID?.() || uid() + uid()).replace(/[^A-Za-z0-9-]/g, "");
      localStorage.setItem("dalil.did", id);
    }
  } catch { /* maxfiy rejim: server IP bo'yicha hisoblaydi */ }
  const h: Record<string, string> = {};
  if (id) h["X-Device-Id"] = id;
  const tg = telegramInitData();
  if (tg) h["X-Telegram-Init-Data"] = tg;
  return h;
}

export async function getQuota(): Promise<Quota | null> {
  try {
    const r = await fetch("/api/quota", { headers: who() });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

const body = (p: AskParams) => JSON.stringify({ ...p, mode: p.mode || "legal" });

type Ctx = {
  sources: Source[]; no_answer: boolean; no_answer_text: string; lang: AnswerLang; parts: string[];
  steps: Step[]; post: PostRules; prompt: { system: string; user: string } | null;
};

/** O'z kaliti bilan: server bosqichlar, manbalar va tayyor so'rovni beradi (/api/context), LLM brauzerdan chaqiriladi.
    Hodisalar /api/ask bilan bir xil, shuning uchun interfeys qaysi yo'l ishlatilganini bilmaydi. */
export async function askDirect(ai: AiConfig, p: AskParams, signal: AbortSignal, h: AskHandlers) {
  const t0 = performance.now();
  let ctx: Ctx;
  try {
    const r = await fetch("/api/context", { method: "POST", headers: { "Content-Type": "application/json" }, body: body(p), signal });
    const d = await r.json().catch(() => null);
    if (!r.ok || !d) {
      h.onError(d?.message ? d : { code: "server", message: `Server xato qaytardi (${r.status}). Qayta urinib koʻring.` });
      return;
    }
    ctx = d;
  } catch {
    if (signal.aborted) return;
    h.onError({ code: "network", message: "Server bilan aloqa yoʻq. Server ishga tushganini tekshirib, qayta urinib koʻring." });
    return;
  }
  for (const s of ctx.steps || []) h.onStep(s);
  h.onSources(ctx);
  const ms = () => Math.round(performance.now() - t0);
  if (ctx.no_answer || !ctx.prompt) {
    h.onDelta(ctx.no_answer_text);
    h.onDone({ no_answer: true, model: null, ms: ms() });
    return;
  }
  // serverdagi rag.AnswerStream bilan bir xil: <<<KEYINGI>>> qismi ajratiladi, kerak bo'lsa kirillga o'giriladi
  const out = new AnswerStream(ctx.post);
  try {
    const model = await streamAi(ai, ctx.prompt.system, ctx.prompt.user, signal, (t) => { const x = out.feed(t); if (x) h.onDelta(x); });
    const rest = out.flush();
    if (rest) h.onDelta(rest);
    const f = out.followups();
    if (f.length) h.onFollowups(f);
    h.onDone({ no_answer: out.notFound(), model, ms: ms() });
  } catch (e) {
    if (signal.aborted) return;
    if (e instanceof AiError) h.onError({ code: e.code, message: e.message });
    else h.onError({ code: "llm", message: "Javob yozishda kutilmagan xato. Qayta urinib koʻring." });
  }
}

/** POST /api/ask ni SSE oqim sifatida o'qiydi (server kaliti, bepul limit):
    step... -> sources -> delta... -> followups -> quota -> done | error */
export async function askStream(p: AskParams, signal: AbortSignal, h: AskHandlers) {
  let res: Response;
  try {
    res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...who() },
      body: body(p),
      signal,
    });
  } catch (e) {
    if (signal.aborted) return;
    h.onError({ code: "network", message: "Server bilan aloqa yoʻq. Server ishga tushganini tekshirib, qayta urinib koʻring." });
    return;
  }
  if (!res.ok || !res.body) {
    h.onError({ code: "server", message: `Server xato qaytardi (${res.status}). Qayta urinib koʻring.` });
    return;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let finished = false;
  const handle = (block: string) => {
    let ev = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) ev = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return;
    const d = JSON.parse(data.join("\n"));
    if (ev === "step") h.onStep(d);
    else if (ev === "sources") h.onSources(d);
    else if (ev === "delta") h.onDelta(d.text);
    else if (ev === "followups") h.onFollowups(d.items || []);
    else if (ev === "quota") h.onQuota?.(d);
    else if (ev === "done") { finished = true; h.onDone(d); }
    else if (ev === "error") { finished = true; h.onError(d); }
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        handle(buf.slice(0, i));
        buf = buf.slice(i + 2);
      }
    }
  } catch (e) {
    if (signal.aborted) return;
    h.onError({ code: "network", message: "Aloqa uzilib qoldi. Qayta urinib koʻring." });
    return;
  }
  if (!finished && !signal.aborted) h.onError({ code: "server", message: "Javob oxirigacha kelmadi. Qayta urinib koʻring." });
}

/** Ishonch tekshiruvi (serverda, LLM'siz): har da'vo iqtibos qilingan moddada asosi bormi */
export async function verifyAnswer(text: string, chunkIds: string[], lang: AnswerLang, mode: Mode): Promise<Trust | null> {
  try {
    const r = await fetch("/api/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, chunk_ids: chunkIds.slice(0, 12), lang, mode }),
    });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export async function getStats(): Promise<Stats | null> {
  try {
    const r = await fetch("/api/stats");
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}
