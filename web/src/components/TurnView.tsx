import { useEffect, useRef, useState } from "react";
import { Icon } from "../icons";
import { renderAnswer } from "../render";
import type { Turn } from "../types";

/* Javob matni so'zma-so'z chiqadi: serverdan kelgan bo'laklar buferga tushadi,
   ekranda esa bir tekis tezlikda ochiladi (bufer kattalashsa tezlashadi). */
function Prose({ turn, live, activeN, onCite, onTick }: {
  turn: Turn; live: boolean; activeN: number | null; onCite: (n: number) => void; onTick: () => void;
}) {
  const full = turn.text;
  const [shown, setShown] = useState(() => (live ? 0 : full.length));
  const pos = useRef(shown);
  const times = useRef<number[] | undefined>(live ? [] : undefined);
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (pos.current >= full.length) return;
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
  if (shown < full.length) {
    const cut = visible.search(/\s\S*$/);
    visible = cut > 0 ? visible.slice(0, cut) : "";
  }
  const html = renderAnswer(visible, { maxN: turn.sources.length, activeN, times: times.current, now });
  return (
    <div className="prose" onClick={(e) => {
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

function Waiting({ status }: { status: Turn["status"] }) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = setInterval(() => setSec(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [status]);
  if (status === "searching") return <>Moddalar qidirilmoqda…</>;
  return <>{sec >= 12 ? `Javob yozilmoqda… ${sec} s (model band boʻlsa biroz choʻziladi)` : "Javob yozilmoqda…"}</>;
}

export function TurnView(props: {
  turn: Turn;
  live: boolean;
  isLast: boolean;
  busy: boolean;
  activeN: number | null;
  panelOn: boolean;
  onCite: (n: number) => void;
  onCopy: () => void;
  onRetry: () => void;
  onSources: () => void;
  onTick: () => void;
}) {
  const t = props.turn;
  const pending = t.status === "searching" || t.status === "writing";
  const n = t.sources.length;
  const head = pending ? <Waiting status={t.status} />
    : t.status === "notfound" ? <>Mos modda topilmadi</>
    : t.status === "error" ? <>{t.error?.code === "no_key" ? "LLM ulanmagan" : "Javob yozilmadi"}</>
    : t.status === "stopped" ? <>Toʻxtatildi</>
    : <>{n} ta modda asosida{t.model ? ` · ${t.model}` : ""}</>;

  const notice = t.status === "notfound" ? (
    <div className="notice" role="status">
      <span className="ic"><Icon name="docq" /></span>
      <div>
        <h4>Bazada mos modda topilmadi</h4>
        <p>Savolga javob beradigan qonun normasi topilmadi, shuning uchun taxmin qilinmadi. Savolni aniqroq yozib koʻring yoki filtrlarni kengaytiring (masalan, “Barchasi”).</p>
      </div>
    </div>
  ) : t.status === "error" && t.error ? (
    <div className={`notice ${t.error.code === "no_key" || t.error.code === "bad_key" ? "key" : "err"}`} role="alert">
      <span className="ic"><Icon name={t.error.code === "no_key" || t.error.code === "bad_key" ? "key" : "alert"} /></span>
      <div>
        <h4>{t.error.code === "no_key" ? "API kalit sozlanmagan" : t.error.code === "bad_key" ? "API kalit notoʻgʻri"
          : t.error.code === "network" ? "Aloqa yoʻq" : t.error.code === "timeout" ? "Vaqt tugadi" : "Xato yuz berdi"}</h4>
        <p>{t.error.message}</p>
        {props.isLast && !props.busy && (
          <button className="retry press" onClick={props.onRetry}><Icon name="redo" />Qayta urinish</button>
        )}
      </div>
    </div>
  ) : null;

  // LLM o'zi "topilmadi" deb yozgan bo'lsa, uning izohi (qayerdan qidirish mumkin) ham ko'rsatiladi
  const showText = !!t.text && !t.noLLM;
  const done = !pending && !(props.live && t.status === "notfound");
  return (
    <div className="turn">
      <div className="u-msg">{t.q}</div>
      <div className="a-msg">
        <div className={`a-head${pending ? " thinking" : ""}`}><span className="mk" /><span>{head}</span></div>
        {t.status === "notfound" && notice}
        {showText ? (
          <Prose turn={t} live={props.live} activeN={props.activeN} onCite={props.onCite} onTick={props.onTick} />
        ) : pending ? <Skeleton /> : null}
        {t.status === "stopped" && !t.text && <p className="stopped-note">Javob toʻxtatildi.</p>}
        {t.status === "error" && notice}
        {done && (
          <div className="a-actions">
            {t.text && t.status !== "notfound" && (
              <button className="cbtn press" onClick={props.onCopy} aria-label="Nusxalash" title="Nusxalash"><Icon name="copy" /></button>
            )}
            {props.isLast && !props.busy && t.status !== "error" && (
              <button className="cbtn press" onClick={props.onRetry} aria-label="Qayta yozish" title="Qayta yozish"><Icon name="redo" /></button>
            )}
            {n > 0 && (
              <>
                <button className="src-pill press mob-src" onClick={props.onSources}>
                  <span className="stk">{t.sources.slice(0, 3).map((s) => <span key={s.n}>{s.n}</span>)}</span>
                  {t.status === "notfound" ? `Eng yaqin ${n} ta modda` : `${n} ta manba`}
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
