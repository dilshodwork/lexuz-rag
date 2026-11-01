import { useEffect, useRef, useState } from "react";
import { Icon } from "../icons";
import { renderAnswer } from "../render";
import { NOT_FOUND_LEAD } from "../textproc";
import type { Mode, Step, Turn, Variant } from "../types";
import { ShareButton } from "./ShareButton";
import { Steps } from "./Steps";
import { TrustBadge, TrustPanel } from "./TrustBadge";

type Mark = { start: number; end: number; i: number };

/* Javob matni so'zma-so'z chiqadi: serverdan kelgan bo'laklar buferga tushadi,
   ekranda esa bir tekis tezlikda ochiladi (bufer kattalashsa tezlashadi). */
function Prose({ text, maxN, live, activeN, marks, onCite, onTick, boxRef }: {
  text: string; maxN: number; live: boolean; activeN: number | null; marks?: Mark[];
  onCite: (n: number) => void; onTick: () => void; boxRef?: React.RefObject<HTMLDivElement | null>;
}) {
  const full = text;
  const [shown, setShown] = useState(() => (live ? 0 : full.length));
  const pos = useRef(shown);
  const times = useRef<number[] | undefined>(live ? [] : undefined);
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (pos.current >= full.length) { pos.current = full.length; setShown(full.length); return; }
    let raf = 0, last = performance.now();
    const tick = (t: number) => {
      const dt = Math.min(64, t - last);
      last = t;
      const backlog = full.length - pos.current;
      const cps = Math.max(90, backlog * 2.2); // belgi/soniya
      pos.current = Math.min(full.length, pos.current + (cps * dt) / 1000);
      setShown(Math.floor(pos.current));
      setNow(t);
      onTick();
      if (pos.current < full.length) raf = requestAnimationFrame(tick);
      else setTimeout(() => setNow(performance.now()), 600); // oxirgi so'zlar animatsiyasi tugashi uchun
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [full]); // eslint-disable-line react-hooks/exhaustive-deps

  // yarim so'z ko'rinmasin: oxirgi bo'sh joygacha kesiladi
  let visible = full.slice(0, shown);
  const complete = shown >= full.length;
  if (!complete) {
    const cut = visible.search(/\s\S*$/);
    visible = cut > 0 ? visible.slice(0, cut) : "";
  }
  // asossiz gaplar faqat matn to'liq ochilgach belgilanadi (o'rinlar to'liq matnga nisbatan)
  const html = renderAnswer(visible, { maxN, activeN, times: times.current, now, marks: complete ? marks : undefined });
  return (
    <div className="prose" ref={boxRef} onClick={(e) => {
      const b = (e.target as HTMLElement).closest(".cite") as HTMLElement | null;
      if (b) onCite(+b.dataset.n!);
    }} dangerouslySetInnerHTML={{ __html: html }} />
  );
}

function Skeleton() {
  return (
    <div className="prose" aria-hidden="true">
      <div className="sk" style={{ width: "94%" }} /><div className="sk" style={{ width: "80%" }} />
      <div className="sk" style={{ width: "88%" }} /><div className="sk" style={{ width: "56%" }} />
    </div>
  );
}

const TITLES: Record<string, string> = {
  no_key: "API kalit sozlanmagan", bad_key: "API kalit notoʻgʻri", network: "Aloqa yoʻq", timeout: "Vaqt tugadi",
  quota: "Kunlik limit tugadi", busy: "LLM band", free_limit: "Bugungi bepul savollar tugadi", no_model: "Model topilmadi",
  region: "Provayder ishlamadi", rate_limit: "Soʻrovlar juda koʻp", loading: "Server tayyorlanmoqda", origin: "Soʻrov rad etildi",
};
// bu xatolarda "AI ulash" oynasi yordam beradi
const KEY_CODES = ["no_key", "bad_key", "quota", "free_limit", "no_model", "region"];

export function TurnView(props: {
  turn: Turn;
  live: Mode | null;   // shu savolning qaysi varianti hozir yozilmoqda
  isLast: boolean;
  busy: boolean;
  activeN: number | null;
  panelOn: boolean;
  onCite: (n: number) => void;
  onCopy: () => void;
  onRetry: () => void;
  onExplain: () => void;
  onView: (m: Mode) => void;
  onFollowup: (q: string) => void;
  onSources: () => void;
  onTick: () => void;
  onConnect: () => void;
  onHud: (m: string) => void;
  onXray: () => void;
  xrayOn: boolean;   // desktop o'ng panelda shu javobning X-ray'i ochiq
}) {
  const t = props.turn;
  const simpleView = t.view === "simple" && !!t.simple;
  const mode: Mode = simpleView ? "simple" : "legal";
  const v: Variant = simpleView ? t.simple! : t;
  const live = props.live === mode;
  const pending = v.status === "searching" || v.status === "writing";
  const n = t.sources.length;
  const [trustOpen, setTrustOpen] = useState(false);
  const proseRef = useRef<HTMLDivElement>(null);
  useEffect(() => setTrustOpen(false), [mode]);

  // bosqichlar: server birinchisini yuborguncha - o'rinbosar
  const steps: Step[] = v.steps?.length ? v.steps
    : pending ? [{ key: "start", label: mode === "simple" ? "Manbalar tayyorlanmoqda" : "Savol tahlil qilinmoqda", state: "run" }] : [];

  const code = v.error?.code || "";
  const keyish = KEY_CODES.includes(code);
  const notice = v.status === "notfound" ? (
    <div className="notice" role="status">
      <span className="ic"><Icon name="docq" /></span>
      <div>
        <h4>Bazada mos modda topilmadi</h4>
        <p>Savolga javob beradigan qonun normasi topilmadi, shuning uchun taxmin qilinmadi. Savolni aniqroq yozib koʻring yoki filtrlarni kengaytiring (masalan, “Barchasi”).</p>
      </div>
    </div>
  ) : v.status === "error" && v.error ? (
    <div className={`notice ${keyish ? "key" : "err"}`} role="alert">
      <span className="ic"><Icon name={keyish ? "key" : "alert"} /></span>
      <div>
        <h4>{TITLES[code] || "Xato yuz berdi"}</h4>
        <p>{v.error.message}</p>
        {props.isLast && !props.busy && (
          <div className="n-actions">
            {keyish && <button className="retry press" onClick={props.onConnect}><Icon name="key" />{code === "free_limit" || code === "no_key" ? "Kalitni ulash" : "AI sozlamalari"}</button>}
            {code !== "free_limit" && <button className={`retry press${keyish ? " ghost" : ""}`} onClick={simpleView ? props.onExplain : props.onRetry}><Icon name="redo" />Qayta urinish</button>}
          </div>
        )}
      </div>
    </div>
  ) : null;

  // LLM o'zi "topilmadi" deb yozgan bo'lsa, uning izohi (qayerdan qidirish mumkin) ham ko'rsatiladi
  const text = v.status === "notfound" ? v.text.replace(NOT_FOUND_LEAD, "") : v.text;
  const showText = !!text.trim() && !v.noLLM;
  const done = !pending && !(live && v.status === "notfound");
  const trust = typeof v.trust === "object" ? v.trust : null;
  const marks: Mark[] | undefined = trust && !live ? trust.claims.map((c, i) => ({ ...c, i })).filter((c) => !c.ok) : undefined;
  const focusClaim = (i: number) => {
    const els = proseRef.current?.querySelectorAll<HTMLElement>(`.wk[data-c="${i}"]`);
    if (!els?.length) return;
    els[0].scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    els.forEach((e) => { e.classList.remove("flash"); void e.offsetWidth; e.classList.add("flash"); });
  };
  const canExplain = t.status === "done" && !!t.text && !t.noLLM && (!t.simple || ["error", "stopped"].includes(t.simple.status));
  const followups = done && props.isLast && !props.busy && (v.status === "done" || v.status === "notfound") ? v.followups || [] : [];

  return (
    <div className="turn">
      <div className="u-msg">{t.q}</div>
      <div className={`a-msg${trustOpen ? " trust-open" : ""}`}>
        {t.simple && (
          <div className="seg mode-seg" data-v={simpleView ? 1 : 0} role="tablist" aria-label="Javob koʻrinishi">
            <span className="thumb" />
            <button role="tab" aria-selected={!simpleView} onClick={() => props.onView("legal")}>Yuridik</button>
            <button role="tab" aria-selected={simpleView} onClick={() => props.onView("simple")}>Sodda</button>
          </div>
        )}
        {steps.length ? (
          <div className="a-top">
            <Steps key={mode} steps={steps} live={pending || live} totalMs={v.ms} />
            {done && <TrustBadge trust={v.trust} open={trustOpen} onToggle={() => setTrustOpen((o) => !o)} />}
          </div>
        ) : (
          // 1-bosqichdan qolgan suhbatlar (bosqichlar saqlanmagan)
          <div className="a-head"><span className="mk" /><span>{v.status === "notfound" ? "Mos modda topilmadi" : v.status === "error" ? "Javob yozilmadi" : v.status === "stopped" ? "Toʻxtatildi" : `${n} ta modda asosida${v.model ? ` · ${v.model}` : ""}`}</span></div>
        )}
        {trustOpen && trust && <TrustPanel trust={trust} text={v.text} simple={simpleView} onFocus={focusClaim} />}
        {v.status === "notfound" && notice}
        {showText ? (
          <Prose key={mode} text={text} maxN={n} live={live} activeN={props.activeN} marks={marks} onCite={props.onCite} onTick={props.onTick} boxRef={proseRef} />
        ) : pending ? <Skeleton /> : null}
        {v.status === "stopped" && !v.text && <p className="stopped-note">Javob toʻxtatildi.</p>}
        {v.status === "error" && notice}
        {followups.length > 0 && (
          <div className="fups" aria-label="Keyingi savollar">
            {followups.map((q) => (
              <button key={q} className="fup press" onClick={() => props.onFollowup(q)}><span>{q}</span><Icon name="arrow" /></button>
            ))}
          </div>
        )}
        {done && (
          <div className="a-actions">
            {v.text && v.status !== "notfound" && (
              <button className="cbtn press" onClick={props.onCopy} aria-label="Nusxalash" title="Nusxalash"><Icon name="copy" /></button>
            )}
            {props.isLast && !props.busy && t.status !== "error" && !simpleView && (
              <button className="cbtn press" onClick={props.onRetry} aria-label="Qayta yozish" title="Qayta yozish"><Icon name="redo" /></button>
            )}
            {v.text && v.status === "done" && (
              <ShareButton item={{ q: t.q, text: v.text, sources: t.sources }} onHud={props.onHud} />
            )}
            {canExplain && !props.busy && (
              <button className="explain press" onClick={props.onExplain}><Icon name="bulb" /><span>Sodda<span className="lg"> qilib tushuntir</span></span></button>
            )}
            {!simpleView && (t.status === "done" || t.status === "notfound") && (
              <button className={`xr-btn press${props.xrayOn ? " on" : ""}${t.xray ? " has" : ""}`} onClick={props.onXray} aria-label="Ichini koʻrish" title="RAG ichini koʻrish: qidiruv, prompt, vaqtlar">
                <Icon name="xray" /><span className="lg">Ichini koʻrish</span>
              </button>
            )}
            {n > 0 && (
              <>
                <button className="src-pill press mob-src" onClick={props.onSources}>
                  <span className="stk">{t.sources.slice(0, 3).map((s) => <span key={s.n}>{s.n}</span>)}</span>
                  {v.status === "notfound" ? `Eng yaqin ${n} ta` : `${n} ta manba`}
                </button>
                {!props.isLast && (
                  <button className={`desk-src press${props.panelOn ? " on" : ""}`} onClick={props.onSources}>Manbalar ({n})</button>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
