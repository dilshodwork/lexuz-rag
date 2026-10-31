import { useRef, useState } from "react";
import { checkAi, maskKey, PROVIDER_IDS, PROVIDERS, viaServer, type AiConfig, type Provider } from "../ai";
import { Icon } from "../icons";
import { haptic, inTelegram, openExternal } from "../telegram";
import type { Quota } from "../types";

const GEMINI_URL = "https://aistudio.google.com/apikey";

/** Bepul Gemini kalit olish: 3 qadam + havola */
export function GeminiGuide({ open: open0 = false }: { open?: boolean }) {
  const [open, setOpen] = useState(open0);
  return (
    <div className={`guide${open ? " open" : ""}`}>
      <button className="guide-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="g-ic"><Icon name="key" /></span>
        <span className="txt">Bepul Gemini kalit olish<small>Gmail hisobi yetarli, 2 daqiqa</small></span>
        <Icon name="down" className="i chev" />
      </button>
      {open && (
        <div className="guide-body">
          <ol>
            <li><b>aistudio.google.com/apikey</b> sahifasini oching va Gmail hisobingiz bilan kiring.</li>
            <li><b>“Create API key”</b> tugmasini bosing.</li>
            <li>Chiqqan kalitni nusxalang va shu yerdagi “API kalit” maydoniga qoʻying.</li>
          </ol>
          <a className="lex guide-btn press" href={GEMINI_URL} target="_blank" rel="noopener noreferrer"
            onClick={(e) => openExternal(GEMINI_URL, e)}>Google AI Studio’ni ochish<Icon name="ext" /></a>
        </div>
      )}
    </div>
  );
}

type Check = { state: "idle" | "checking" | "ok" | "bad_key" | "quota" | "error"; message?: string };

function StatusBox({ ai, quota, check }: { ai: AiConfig | null; quota: Quota | null; check: Check }) {
  let tone = "off", title: string, sub: string;
  if (check.state === "checking") { tone = "wait"; title = "Tekshirilmoqda…"; sub = "Provayderga kichik sinov soʻrovi yuborildi"; }
  else if (check.state !== "idle") {
    tone = check.state === "ok" ? "on" : check.state === "quota" ? "warn" : "err";
    title = check.state === "ok" ? "Ulangan" : check.state === "bad_key" ? "Kalit qabul qilinmadi" : check.state === "quota" ? "Kalit toʻgʻri, lekin limit tugagan" : "Tekshirib boʻlmadi";
    sub = check.message || "";
  } else if (ai) {
    const p = PROVIDERS[ai.provider].short;
    tone = ai.status === "ok" || ai.status === "unchecked" ? "on" : ai.status === "quota" ? "warn" : "err";
    title = ai.status === "bad_key" ? "Kalit qabul qilinmadi" : ai.status === "quota" ? "Limit tugagan" : "Ulangan";
    sub = `${p} · ${ai.model} · kalit ${maskKey(ai.key)}`;
  } else {
    title = "Oʻz AI hisobingiz ulanmagan";
    sub = quota?.free ? `Bepul rejim: bugun ${quota.left}/${quota.limit} savol qoldi` : "Serverda bepul AI yoʻq — javob uchun kalit kerak";
  }
  return (
    <div className={`ai-status tone-${tone}`} role="status" aria-live="polite">
      <span className="dot" />
      <div><b>{title}</b><small>{sub}</small></div>
    </div>
  );
}

/** "AI ulash": provayder, kalit, model, tekshirish. Kalit faqat shu qurilmada saqlanadi (ai.ts) */
export function AiConnect({ ai, quota, onSave }: { ai: AiConfig | null; quota: Quota | null; onSave: (c: AiConfig | null) => void }) {
  const [provider, setProvider] = useState<Provider>(ai?.provider || "gemini");
  const [key, setKey] = useState(ai?.key || "");
  const [model, setModel] = useState(ai?.model || PROVIDERS[ai?.provider || "gemini"].models[0].id);
  const [show, setShow] = useState(false);
  const [check, setCheck] = useState<Check>({ state: "idle" });
  const statusRef = useRef<HTMLDivElement>(null);
  const P = PROVIDERS[provider];
  const dirty = !ai || ai.provider !== provider || ai.key !== key.trim() || ai.model !== model;

  const pick = (p: Provider) => {
    if (p === provider) return;
    haptic();
    setProvider(p);
    setModel(PROVIDERS[p].models[0].id);
    setKey(ai?.provider === p ? ai.key : "");
    setCheck({ state: "idle" });
  };

  const verify = async () => {
    const k = key.trim();
    if (!k) { setCheck({ state: "error", message: "Avval API kalitni kiriting." }); return; }
    setCheck({ state: "checking" });
    const cfg: AiConfig = { provider, model, key: k, status: "unchecked" };
    const r = await checkAi(cfg);
    haptic();
    setCheck({ state: r.status === "unchecked" ? "ok" : r.status, message: r.message });
    // natija tepadagi holat kartochkasida: tugma pastda bo'lgani uchun unga qaytiladi
    requestAnimationFrame(() => statusRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    // to'g'ri kalit saqlanadi (limiti tugagan bo'lsa ham: ertaga ishlaydi); noto'g'ri kalit saqlanmaydi
    if (r.status === "ok" || r.status === "quota") onSave({ ...cfg, status: r.status, at: Date.now() });
  };

  const remove = () => {
    if (!confirm("Kalit shu qurilmadan oʻchirilsinmi?")) return;
    onSave(null);
    setKey("");
    setCheck({ state: "idle" });
  };

  return (
    <div className="ai-form">
      <p className="ai-lead">{viaServer(provider)
        ? "Javoblar oʻz AI hisobingiz orqali yoziladi. Kalit faqat shu qurilmada saqlanadi. OpenAI brauzerdan toʻgʻridan-toʻgʻri soʻrovni toʻliq qoʻllamaydi, shuning uchun soʻrov Dalil serveri orqali oʻtadi — kalit hech qayerga yozilmaydi."
        : "Javoblar oʻz AI hisobingiz orqali yoziladi. Kalit faqat shu qurilmada saqlanadi va toʻgʻridan-toʻgʻri provayderga yuboriladi — Dalil serveriga emas."}</p>
      <div ref={statusRef} className="ai-status-wrap"><StatusBox ai={ai} quota={quota} check={check} /></div>

      <div className="grp-label">Provayder</div>
      <div className="seg seg3" data-v={PROVIDER_IDS.indexOf(provider)} role="radiogroup" aria-label="Provayder">
        <span className="thumb" />
        {PROVIDER_IDS.map((p) => (
          <button key={p} role="radio" aria-checked={p === provider} onClick={() => pick(p)}>{PROVIDERS[p].short}</button>
        ))}
      </div>

      <div className="grp-label">API kalit</div>
      <div className="grp">
        <label className="row keyrow">
          <input type={show ? "text" : "password"} value={key} onChange={(e) => { setKey(e.target.value); setCheck({ state: "idle" }); }}
            placeholder={P.placeholder} autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false}
            aria-label={`${P.name} API kaliti`} name="dalil-ai-key" data-1p-ignore />
          <button type="button" className="eye press" onClick={() => setShow(!show)} aria-label={show ? "Kalitni yashirish" : "Kalitni koʻrsatish"}>
            <Icon name={show ? "eyeoff" : "eye"} />
          </button>
        </label>
      </div>
      {provider === "gemini" ? <GeminiGuide open={!ai && !key} /> : (
        <p className="f-hint">Kalitni olish: <a href={P.keyUrl} target="_blank" rel="noopener noreferrer" onClick={(e) => openExternal(P.keyUrl, e)}>{P.keyHost}</a> (hisobda toʻlov usuli boʻlishi kerak).</p>
      )}

      <div className="grp-label">Model</div>
      <div className="grp">
        {P.models.map((m) => (
          <button key={m.id} className={`row${m.id === model ? " on" : ""}`} role="radio" aria-checked={m.id === model}
            onClick={() => { setModel(m.id); setCheck({ state: "idle" }); }}>
            <span className="txt"><span className="mono">{m.id}</span><small>{m.hint}</small></span>
            <Icon name="check" className="i chk" />
          </button>
        ))}
      </div>

      <button className="primary press" onClick={verify} disabled={check.state === "checking"}>
        {check.state === "checking" ? "Tekshirilmoqda…" : dirty ? "Tekshirish va ulash" : "Qayta tekshirish"}
      </button>
      {ai && <button className="linkbtn danger" onClick={remove}>Kalitni oʻchirish</button>}
      <p className="f-hint ai-foot">
        {inTelegram ? "Telegram ichida kalit Telegram bulutli xotirasida ham saqlanadi (faqat sizga koʻrinadi). " : ""}
        “Tekshirish” bir necha tokenlik sinov soʻrovini yuboradi.
      </p>
    </div>
  );
}

/** Bepul savollar tugaganda */
export function LimitPanel({ quota, onConnect, onLater }: { quota: Quota | null; onConnect: () => void; onLater: () => void }) {
  const global = quota?.reason === "global";
  return (
    <div className="limit">
      <div className="limit-orb" aria-hidden="true"><Icon name="key" /></div>
      <h3>{global ? "Bugungi umumiy bepul limit tugadi" : "Bugungi bepul savollar tugadi"}</h3>
      <p>{global
        ? "Server kaliti hamma uchun birgalikda ishlaydi va bugungi ulushi tugadi. Oʻz AI kalitingizni ulang — Gemini kaliti bepul va 2 daqiqada olinadi."
        : `Har kuni ${quota?.limit || 5} ta savol bepul. Davom etish uchun oʻz AI kalitingizni ulang — Gemini kaliti bepul va 2 daqiqada olinadi. Ertaga yana bepul savollar beriladi.`}</p>
      <GeminiGuide open />
      <button className="primary press" onClick={onConnect}>Oʻz kalitingizni ulang</button>
      <button className="linkbtn" onClick={onLater}>Keyinroq</button>
    </div>
  );
}
