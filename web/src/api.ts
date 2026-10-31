import { AiError, streamAi, type AiConfig } from "./ai";
import { uid } from "./store";
import { telegramInitData } from "./telegram";
import type { Filters, Quota, Source, Stats } from "./types";

export type AskHandlers = {
  onSources: (d: { sources: Source[]; no_answer: boolean }) => void;
  onDelta: (text: string) => void;
  onDone: (d: { no_answer: boolean; model: string | null; ms: number }) => void;
  onError: (d: { code: string; message: string }) => void;
  onQuota?: (q: Quota) => void;
};

// LLM manbalarda javob topmasa shu iborani yozadi (rag.SYSTEM, 4-qoida; serverdagi NOT_FOUND_RE bilan bir xil)
const NOT_FOUND = /^\W*Bazadagi hujjatlarda bu savolga[^.]*topilmadi/i;

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

/** O'z kaliti bilan: server manbalar va tayyor so'rovni beradi (/api/context), LLM brauzerdan chaqiriladi.
    Hodisalar /api/ask bilan bir xil, shuning uchun interfeys qaysi yo'l ishlatilganini bilmaydi. */
export async function askDirect(ai: AiConfig, question: string, filters: Filters, signal: AbortSignal, h: AskHandlers) {
  const t0 = performance.now();
  let ctx: { sources: Source[]; no_answer: boolean; no_answer_text: string; prompt: { system: string; user: string } | null };
  try {
    const r = await fetch("/api/context", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, filters }), signal,
    });
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
  h.onSources(ctx);
  const ms = () => Math.round(performance.now() - t0);
  if (ctx.no_answer || !ctx.prompt) {
    h.onDelta(ctx.no_answer_text);
    h.onDone({ no_answer: true, model: null, ms: ms() });
    return;
  }
  let text = "";
  try {
    const model = await streamAi(ai, ctx.prompt.system, ctx.prompt.user, signal, (t) => { text += t; h.onDelta(t); });
    h.onDone({ no_answer: NOT_FOUND.test(text), model, ms: ms() });
  } catch (e) {
    if (signal.aborted) return;
    if (e instanceof AiError) h.onError({ code: e.code, message: e.message });
    else h.onError({ code: "llm", message: "Javob yozishda kutilmagan xato. Qayta urinib koʻring." });
  }
}

/** POST /api/ask ni SSE oqim sifatida o'qiydi (server kaliti, bepul limit): sources -> delta... -> quota -> done | error */
export async function askStream(question: string, filters: Filters, signal: AbortSignal, h: AskHandlers) {
  let res: Response;
  try {
    res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...who() },
      body: JSON.stringify({ question, filters }),
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
    if (ev === "sources") h.onSources(d);
    else if (ev === "delta") h.onDelta(d.text);
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

export async function getStats(): Promise<Stats | null> {
  try {
    const r = await fetch("/api/stats");
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}
