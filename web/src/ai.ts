/* "AI ulash": foydalanuvchining o'z AI kaliti (BYOK).
   * Kalit faqat shu qurilmada: localStorage, Telegram ichida CloudStorage ham (boshqa qurilmadagi Telegram'da ham ishlashi uchun).
   * Dalil serveri faqat manbalar va tayyor so'rov matnini beradi (/api/context), LLM'ni brauzer o'zi chaqiradi:
     Gemini va Claude - to'g'ridan-to'g'ri (kalit serverga umuman kelmaydi). OpenAI xato javoblarida CORS sarlavhasi
     yo'q, shuning uchun u /api/proxy/openai orqali: kalit faqat so'rov sarlavhasida o'tadi, saqlanmaydi. */
import { cloudStorage } from "./telegram";

export type Provider = "gemini" | "openai" | "anthropic";
/** unchecked: saqlangan, lekin hali so'rov yuborilmagan */
export type AiStatus = "ok" | "bad_key" | "quota" | "unchecked";
export type AiConfig = { provider: Provider; model: string; key: string; status: AiStatus; at?: number };
export type ModelOpt = { id: string; hint: string };

export const PROVIDERS: Record<Provider, { name: string; short: string; placeholder: string; keyUrl: string; keyHost: string; models: ModelOpt[] }> = {
  gemini: {
    name: "Google Gemini", short: "Gemini", placeholder: "AIza…", keyUrl: "https://aistudio.google.com/apikey", keyHost: "aistudio.google.com",
    models: [
      { id: "gemini-3.5-flash", hint: "Tavsiya: tez va aniq" },
      { id: "gemini-3.1-flash-lite", hint: "Eng tez, bepul limiti kattaroq" },
      { id: "gemini-3.8-flash", hint: "Eng yangi, baʼzan band" },
    ],
  },
  openai: {
    name: "OpenAI", short: "OpenAI", placeholder: "sk-…", keyUrl: "https://platform.openai.com/api-keys", keyHost: "platform.openai.com",
    models: [
      { id: "gpt-4.1-mini", hint: "Tavsiya: tez va arzon" },
      { id: "gpt-4.1-nano", hint: "Eng arzon" },
      { id: "gpt-5-mini", hint: "Sifatliroq, sekinroq" },
    ],
  },
  anthropic: {
    name: "Anthropic Claude", short: "Claude", placeholder: "sk-ant-…", keyUrl: "https://console.anthropic.com/settings/keys", keyHost: "console.anthropic.com",
    models: [
      { id: "claude-haiku-5-5", hint: "Tavsiya: tez va arzon" },
      { id: "claude-sonnet-5-5", hint: "Sifatliroq" },
      { id: "claude-haiku-4-5", hint: "Oldingi avlod, arzon" },
    ],
  },
};
export const PROVIDER_IDS = Object.keys(PROVIDERS) as Provider[];

// ---------------------------------------------------------------- saqlash
const LS = "dalil.ai.v1";
const CS = "dalil_ai_v1"; // CloudStorage kalit nomida nuqta bo'lmaydi

function valid(x: unknown): AiConfig | null {
  const c = x as AiConfig | null;
  if (!c || !PROVIDER_IDS.includes(c.provider) || typeof c.key !== "string" || !c.key || typeof c.model !== "string") return null;
  return { provider: c.provider, model: c.model || PROVIDERS[c.provider].models[0].id, key: c.key,
    status: (["ok", "bad_key", "quota", "unchecked"] as AiStatus[]).includes(c.status) ? c.status : "unchecked", at: c.at };
}
const parse = (s: string | null) => { try { return s ? valid(JSON.parse(s)) : null; } catch { return null; } };

export function loadAi(): AiConfig | null {
  try { return parse(localStorage.getItem(LS)); } catch { return null; }
}

/** Telegram'da bulutdagi nusxa. undefined - bulut yo'q (oddiy brauzer), null - bulutda kalit yo'q */
export async function loadAiCloud(): Promise<AiConfig | null | undefined> {
  const cs = cloudStorage();
  if (!cs) return undefined;
  const v = await cs.get(CS);
  return v === null ? undefined : parse(v);
}

export function saveAi(c: AiConfig | null) {
  const cs = cloudStorage();
  try {
    if (c) localStorage.setItem(LS, JSON.stringify(c)); else localStorage.removeItem(LS);
  } catch { /* maxfiy rejim: faqat shu sessiya */ }
  if (cs) { if (c) cs.set(CS, JSON.stringify(c)); else cs.remove(CS); }
}

export const maskKey = (k: string) => (k.length > 10 ? `${k.slice(0, 4)}…${k.slice(-4)}` : "••••");

// ---------------------------------------------------------------- xatolar
export type AiErrCode = "bad_key" | "quota" | "busy" | "no_model" | "region" | "network" | "timeout" | "llm";
export class AiError extends Error {
  started = false; // javobning bir qismi chiqib bo'lgan (zaxira modelga o'tib bo'lmaydi)
  constructor(public code: AiErrCode, message: string, public detail = "") { super(message); }
}

function human(p: Provider, model: string, code: AiErrCode, detail = ""): AiError {
  const P = PROVIDERS[p].short;
  const m: Record<AiErrCode, string> = {
    bad_key: `${P} kalitingiz qabul qilinmadi: notoʻgʻri, oʻchirilgan yoki muddati oʻtgan. “AI ulash” boʻlimida kalitni tekshiring.`,
    quota: p === "gemini"
      ? `${P} kalitingizning bugungi bepul limiti tugadi (${model}). Ertaga qayta urinib koʻring yoki “AI ulash”da boshqa model tanlang.`
      : `${P} hisobingizda mablagʻ yoki limit qolmagan. ${PROVIDERS[p].keyHost} saytida Billing boʻlimini tekshiring.`,
    busy: `${P} hozir band yoki daqiqalik limitga yetdingiz. Bir daqiqadan keyin qayta urinib koʻring.`,
    no_model: `“${model}” modeli bu kalitga berilmaydi yoki mavjud emas. “AI ulash”da boshqa modelni tanlang.`,
    region: `${P} bu hududda yoki bu hisob uchun ishlamaydi. Boshqa provayderni tanlab koʻring.`,
    network: `${P} serveriga ulanib boʻlmadi. Internetni tekshiring; baʼzi tarmoqlar (VPN, korporativ Wi-Fi) bu xizmatni toʻsadi.`,
    timeout: `${P} javob berishga ulgurmadi (vaqt tugadi). Qayta urinib koʻring.`,
    llm: `${P} xato qaytardi. Birozdan keyin qayta urinib koʻring.`,
  };
  return new AiError(code, m[code], detail);
}

async function httpError(p: Provider, model: string, r: Response): Promise<AiError> {
  let t = "";
  try { t = await r.text(); } catch { /* bo'sh */ }
  const s = r.status, detail = `${s} ${t.slice(0, 300)}`;
  const has = (re: RegExp) => re.test(t);
  let code: AiErrCode = "llm";
  if (has(/dalil_network/)) code = "network"; // OpenAI proksisi provayderga ulana olmadi
  else if (has(/API_KEY_INVALID|API key not valid|invalid_api_key|Incorrect API key|authentication_error|invalid x-api-key/i) || s === 401) code = "bad_key";
  else if (has(/location is not supported|unsupported_country|not available in your country/i)) code = "region";
  else if (s === 403) code = has(/PERMISSION_DENIED|permission_error/i) && !has(/API_KEY|key/i) ? "region" : "bad_key";
  else if (s === 404 || has(/model_not_found|not_found_error/i)) code = "no_model";
  else if (has(/insufficient_quota|credit balance is too low|billing/i)) code = "quota";
  else if (s === 429) code = p === "gemini" && has(/PerDay|per day|daily/i) ? "quota" : "busy";
  else if (s === 500 || s === 502 || s === 503 || s === 529 || has(/overloaded_error/)) code = "busy";
  else if (s === 400 && p === "gemini" && has(/API key/i)) code = "bad_key";
  return human(p, model, code, detail);
}

// ---------------------------------------------------------------- so'rovlar
type Req = { url: string; init: RequestInit };
const OPENAI_PROXY = "/api/proxy/openai/chat/completions";
/** Kalit Dalil serveri orqali o'tadimi (faqat so'rov sarlavhasida, saqlanmaydi) */
export const viaServer = (p: Provider) => p === "openai";

function buildReq(c: AiConfig, model: string, system: string, user: string, stream: boolean, maxTokens: number): Req {
  const json = (headers: Record<string, string>, body: unknown): RequestInit =>
    ({ method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
  if (c.provider === "gemini") {
    const fn = stream ? "streamGenerateContent?alt=sse" : "generateContent";
    return {
      url: `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:${fn}`,
      init: json({ "x-goog-api-key": c.key }, {
        ...(system ? { system_instruction: { parts: [{ text: system }] } } : {}),
        contents: [{ role: "user", parts: [{ text: user }] }],
        generationConfig: { temperature: 0.1, maxOutputTokens: maxTokens },
      }),
    };
  }
  if (c.provider === "openai") {
    const reasoning = /^(gpt-5|o\d)/.test(model); // bu modellar temperature'ni qabul qilmaydi
    return {
      // OpenAI xato javoblarida CORS sarlavhasi yo'q (401 "tarmoq xatosi" bo'lib ko'rinardi) - server orqali, kalit saqlanmaydi
      url: OPENAI_PROXY,
      init: json({ Authorization: `Bearer ${c.key}` }, {
        model, stream, max_completion_tokens: maxTokens, ...(reasoning ? {} : { temperature: 0.1 }),
        messages: [...(system ? [{ role: "system", content: system }] : []), { role: "user", content: user }],
      }),
    };
  }
  return {
    url: "https://api.anthropic.com/v1/messages",
    init: json({ "x-api-key": c.key, "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true" }, {
      model, max_tokens: maxTokens, stream, ...(system ? { system } : {}), messages: [{ role: "user", content: user }],
    }),
  };
}

/** SSE "data:" qatoridan matn bo'lagi (yoki oqim ichidagi xato) */
function pieceOf(p: Provider, model: string, d: Record<string, any>): string { // eslint-disable-line @typescript-eslint/no-explicit-any
  if (p === "gemini") {
    if (d.error) throw human(p, model, d.error.code === 429 ? "busy" : "llm", JSON.stringify(d.error).slice(0, 300));
    return (d.candidates || []).flatMap((c: any) => c.content?.parts || []) // eslint-disable-line @typescript-eslint/no-explicit-any
      .filter((x: any) => x.text && !x.thought).map((x: any) => x.text).join(""); // eslint-disable-line @typescript-eslint/no-explicit-any
  }
  if (p === "openai") {
    if (d.error) throw human(p, model, "llm", JSON.stringify(d.error).slice(0, 300));
    return d.choices?.[0]?.delta?.content || "";
  }
  if (d.type === "error") throw human(p, model, d.error?.type === "overloaded_error" ? "busy" : "llm", JSON.stringify(d.error).slice(0, 300));
  return d.type === "content_block_delta" && d.delta?.type === "text_delta" ? d.delta.text || "" : "";
}

const IDLE_MS = 60000; // bo'laklar orasidagi eng uzoq kutish

async function streamOnce(c: AiConfig, model: string, system: string, user: string, signal: AbortSignal, onText: (t: string) => void) {
  const ac = new AbortController();
  let timedOut = false;
  let timer = 0;
  const arm = () => { clearTimeout(timer); timer = window.setTimeout(() => { timedOut = true; ac.abort(); }, IDLE_MS); };
  const stop = () => ac.abort();
  signal.addEventListener("abort", stop);
  const { url, init } = buildReq(c, model, system, user, true, 8192);
  let started = false;
  try {
    arm();
    let r: Response;
    try {
      r = await fetch(url, { ...init, signal: ac.signal, referrerPolicy: "no-referrer" });
    } catch (e) {
      if (signal.aborted) throw e;
      throw human(c.provider, model, timedOut ? "timeout" : "network", String(e));
    }
    if (!r.ok || !r.body) throw await httpError(c.provider, model, r);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (e) {
        if (signal.aborted) throw e;
        throw human(c.provider, model, timedOut ? "timeout" : "network", String(e));
      }
      if (chunk.done) break;
      arm();
      buf += dec.decode(chunk.value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).replace(/\r$/, "");
        buf = buf.slice(i + 1);
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw || raw === "[DONE]") continue;
        let d;
        try { d = JSON.parse(raw); } catch { continue; }
        const t = pieceOf(c.provider, model, d);
        if (t) { started = true; onText(t); }
      }
    }
  } catch (e) {
    if (e instanceof AiError) e.started = started;
    throw e;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", stop);
  }
}

/** Javobni oqim bilan yozadi. Gemini band/limit/404 bo'lsa (birinchi bo'lak chiqmaguncha) ro'yxatdagi
    keyingi modelga o'tadi - serverdagi llm.stream bilan bir xil mantiq. Qaytaradi: javob yozgan model. */
export async function streamAi(c: AiConfig, system: string, user: string, signal: AbortSignal, onText: (t: string) => void): Promise<string> {
  const chain = c.provider === "gemini" ? [c.model, ...PROVIDERS.gemini.models.map((m) => m.id).filter((m) => m !== c.model)] : [c.model];
  let first: AiError | null = null;
  for (const m of chain) {
    try {
      await streamOnce(c, m, system, user, signal, onText);
      return m;
    } catch (e) {
      if (!(e instanceof AiError) || e.started || !["busy", "quota", "no_model"].includes(e.code)) throw e;
      first = first || e;
    }
  }
  throw first!;
}

/** "Tekshirish": kichik so'rov (bir necha token). Kalit, model va limitni bir yo'la tekshiradi. */
export async function checkAi(c: AiConfig): Promise<{ status: AiStatus | "error"; message: string }> {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 25000);
  const { url, init } = buildReq(c, c.model, "", "Salom", false, c.provider === "anthropic" ? 1 : 16);
  try {
    const r = await fetch(url, { ...init, signal: ac.signal, referrerPolicy: "no-referrer" });
    if (r.ok) return { status: "ok", message: `Ulandi: ${PROVIDERS[c.provider].short} · ${c.model}` };
    const e = await httpError(c.provider, c.model, r);
    if (e.code === "bad_key") {
      return { status: "bad_key", message: `${PROVIDERS[c.provider].short} bu kalitni rad etdi: notoʻgʻri, oʻchirilgan yoki muddati oʻtgan. Kalitni qaytadan toʻliq nusxalab qoʻying.` };
    }
    return { status: e.code === "quota" ? "quota" : "error", message: e.message };
  } catch {
    return { status: "error", message: human(c.provider, c.model, ac.signal.aborted ? "timeout" : "network").message };
  } finally {
    clearTimeout(t);
  }
}
