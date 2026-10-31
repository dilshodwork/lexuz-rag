import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { askStream, getStats } from "./api";
import { FilterForm } from "./components/FilterForm";
import { Sheet, type SheetPos } from "./components/Sheet";
import { SkeletonCards, SourceCard } from "./components/SourceCard";
import { TurnView } from "./components/TurnView";
import { Icon, type IconName } from "./icons";
import { plainAnswer } from "./render";
import {
  dayGroup, filtersLabel, isDefaultFilters, loadConvs, loadFilters, loadTheme, saveConvs, saveFilters, saveTheme, timeLabel, uid,
} from "./store";
import { haptic, initTelegram, setBackButton, setTelegramChrome, telegramScheme } from "./telegram";
import type { Conv, Filters, Stats, Turn } from "./types";

const SUGS: { q: string; tag: string; icon: IconName; tall?: boolean }[] = [
  { q: "Prezident qancha muddatga saylanadi?", tag: "Konstitutsiya", icon: "scale", tall: true },
  { q: "Yillik mehnat taʼtili necha kun?", tag: "Mehnat", icon: "brief" },
  { q: "Ijara shartnomasi qanday shaklda tuziladi?", tag: "Fuqarolik", icon: "home" },
  { q: "Ажралиш учун қандай ҳужжатлар керак?", tag: "Oila · kirillcha", icon: "users" },
  { q: "Haydovchilik guvohnomasi necha yilga beriladi?", tag: "Yoʻl harakati", icon: "car" },
];
const PLACEHOLDER = "Savol yozing: lotin yoki кирилл";
const BG = { light: "#F6F4F2", dark: "#120E0F" };
const fmtNum = (n: number | null | undefined, d: string) => (n ? n.toLocaleString("fr-FR").replace(/ | /g, " ") : d);

const useDesktop = () => {
  const q = "(min-width: 1024px)";
  const [v, set] = useState(() => matchMedia(q).matches);
  useEffect(() => {
    const m = matchMedia(q);
    const f = () => set(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  return v;
};

/** Holatni o'zgartirish View Transition bilan (kompozer markazdan pastga suzadi) */
function vt(fn: () => void) {
  const d = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  if (d.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) d.startViewTransition(() => flushSync(fn));
  else fn();
}

export default function App() {
  const desk = useDesktop();
  const [convs, setConvs] = useState<Conv[]>(loadConvs);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(loadFilters);
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    loadTheme() || telegramScheme() || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  const [stats, setStats] = useState<Stats | null>(null);
  const [q, setQ] = useState("");
  const [liveId, setLiveId] = useState<string | null>(null); // hozir oqayotgan javob
  const [panelTurn, setPanelTurn] = useState<string | null>(null); // manbalar paneli qaysi javobniki
  const [hl, setHl] = useState<{ turn: string; n: number } | null>(null);
  const [sheet, setSheet] = useState<{ name: "sources" | "filters" | "history"; pos: SheetPos } | null>(null);
  const [pop, setPop] = useState(false);
  const [hud, setHud] = useState<string | null>(null);
  const [histQ, setHistQ] = useState("");
  const [scrolled, setScrolled] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const deskBody = useRef<HTMLDivElement>(null);
  const mobBody = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const stick = useRef(true); // foydalanuvchi pastda bo'lsa oqim bilan birga pastga suriladi

  const conv = convs.find((c) => c.id === activeId) || null;
  const chat = !!conv;
  const busy = !!liveId;
  const panel = conv ? conv.turns.find((t) => t.id === panelTurn) || conv.turns[conv.turns.length - 1] : null;

  // ---------------------------------------------------------- tashqi muhit
  useEffect(() => { getStats().then(setStats); }, []);
  useEffect(() => { initTelegram((s) => { if (!loadTheme()) setTheme(s); }); }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", BG[theme]);
    setTelegramChrome(BG[theme]);
  }, [theme]);
  useEffect(() => { saveFilters(filters); }, [filters]);
  useEffect(() => { if (!busy) saveConvs(convs); }, [convs, busy]);
  useEffect(() => {
    const b = document.body.classList;
    b.toggle("v-chat", chat);
    b.toggle("busy", busy);
    b.toggle("sheet-open", !!sheet && sheet.pos !== "closed");
    b.toggle("card-mode", !!sheet && sheet.pos === "large");
    b.toggle("pop-open", pop && desk);
  }, [chat, busy, sheet, pop, desk]);
  useEffect(() => { if (desk && sheet) setSheet(null); }, [desk]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { document.title = conv ? `${conv.title} · Dalil` : "Dalil · Qonunchilik boʻyicha savol-javob"; }, [conv]);

  // ---------------------------------------------------------- yordamchilar
  const patchTurn = useCallback((cid: string, tid: string, p: Partial<Turn> | ((t: Turn) => Partial<Turn>)) => {
    setConvs((cs) => cs.map((c) => c.id !== cid ? c : {
      ...c, updated: Date.now(),
      turns: c.turns.map((t) => (t.id !== tid ? t : { ...t, ...(typeof p === "function" ? p(t) : p) })),
    }));
  }, []);

  const showHud = (m: string) => { setHud(m); haptic(); setTimeout(() => setHud(null), 1700); };
  const closeAll = () => { setSheet((s) => (s ? { ...s, pos: "closed" } : s)); setPop(false); };
  const toBottom = (smooth = false) => {
    const s = scrollRef.current;
    if (s) s.scrollTo({ top: s.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  };

  const goHome = () => {
    abort.current?.abort();
    vt(() => { setActiveId(null); setLiveId(null); setHl(null); setPanelTurn(null); setPop(false); setSheet(null); });
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 0 }));
  };

  const run = (cid: string, turn: Turn) => {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    setLiveId(turn.id);
    setPanelTurn(turn.id);
    setHl(null);
    stick.current = true;
    const end = () => { if (abort.current === ac) { abort.current = null; setLiveId(null); } };
    askStream(turn.q, filters, ac.signal, {
      // no_answer: eng yaqin modda ham juda uzoq, LLM chaqirilmaydi -> darhol "topilmadi"
      onSources: (d) => patchTurn(cid, turn.id, d.no_answer ? { sources: d.sources, status: "notfound", noLLM: true } : { sources: d.sources, status: "writing" }),
      onDelta: (text) => patchTurn(cid, turn.id, (t) => (t.noLLM ? {} : { text: t.text + text, status: "writing" })),
      onDone: (d) => { patchTurn(cid, turn.id, { status: d.no_answer ? "notfound" : "done", model: d.model, ms: d.ms }); end(); },
      onError: (e) => { patchTurn(cid, turn.id, { status: "error", error: e }); end(); },
    }).finally(() => {
      if (ac.signal.aborted) patchTurn(cid, turn.id, (t) => (t.status === "searching" || t.status === "writing" ? { status: "stopped" } : {}));
      end();
    });
  };

  const ask = (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setQ("");
    closeAll();
    haptic();
    const turn: Turn = { id: uid(), q: question, text: "", sources: [], status: "searching", at: Date.now() };
    const cid = conv ? conv.id : uid();
    if (conv) {
      setConvs((cs) => [{ ...conv, updated: Date.now(), turns: [...conv.turns, turn] }, ...cs.filter((c) => c.id !== conv.id)]);
    } else {
      // suhbat holatga darhol qo'shiladi (oqim hodisalari uni topa olishi uchun), ko'rinish esa View Transition bilan almashadi
      const c: Conv = { id: cid, title: question, created: Date.now(), updated: Date.now(), turns: [turn] };
      setConvs((cs) => [c, ...cs]);
      vt(() => setActiveId(cid));
    }
    run(cid, turn);
    requestAnimationFrame(() => toBottom(true));
    if (!desk) inputRef.current?.blur();
  };

  const retry = (t: Turn) => {
    if (!conv || busy) return;
    patchTurn(conv.id, t.id, { text: "", sources: [], status: "searching", error: undefined, model: null, noLLM: false });
    run(conv.id, { ...t, text: "", sources: [] });
  };

  const stop = () => abort.current?.abort();

  const copy = async (t: Turn) => {
    const txt = plainAnswer(t.text, t.sources);
    try {
      await navigator.clipboard.writeText(txt);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = txt;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    showHud("Javob nusxalandi");
  };

  /** [n] bosilganda: tegishli manba kartochkasi yoritiladi va unga scroll qilinadi */
  const focusSource = (t: Turn, n: number) => {
    setPanelTurn(t.id);
    setHl({ turn: t.id, n });
    haptic();
    const mobileOpen = !desk && !(sheet?.name === "sources" && sheet.pos !== "closed");
    if (!desk && mobileOpen) setSheet({ name: "sources", pos: "medium" });
    setTimeout(() => {
      const box = desk ? deskBody.current : mobBody.current;
      const card = box?.querySelector<HTMLElement>(`[data-n="${n}"]`)?.closest(".card-wrap")?.firstElementChild as HTMLElement | null;
      if (box && card) box.scrollTo({ top: card.offsetTop - box.offsetTop - 12, behavior: "smooth" });
    }, desk ? 30 : mobileOpen ? 300 : 30);
  };

  const openConv = (id: string) => {
    abort.current?.abort();
    const go = () => { setActiveId(id); setPanelTurn(null); setHl(null); setSheet(null); };
    if (chat) go(); else vt(go);
    requestAnimationFrame(() => toBottom());
  };

  const clearHistory = () => {
    if (!confirm("Barcha suhbatlar oʻchirilsinmi?")) return;
    abort.current?.abort();
    setConvs([]);
    setActiveId(null);
    setSheet(null);
  };

  // Telegram "orqaga" tugmasi
  useEffect(() => { setBackButton(chat ? goHome : null); }, [chat]); // eslint-disable-line react-hooks/exhaustive-deps

  // Desktop popover tashqariga bosilganda yopiladi, Esc hammasini yopadi
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") closeAll(); };
    const c = (e: MouseEvent) => {
      const el = e.target as HTMLElement;
      if (pop && !el.closest("#pop") && !el.closest("[data-filters]")) setPop(false);
    };
    addEventListener("keydown", k);
    addEventListener("mousedown", c);
    return () => { removeEventListener("keydown", k); removeEventListener("mousedown", c); };
  }, [pop]);

  // tarix guruhlari
  const groups = useMemo(() => {
    const qq = histQ.trim().toLowerCase();
    const list = convs.filter((c) => !qq || c.title.toLowerCase().includes(qq) || c.turns.some((t) => t.q.toLowerCase().includes(qq)));
    const g: [string, Conv[]][] = [];
    for (const c of list) {
      const k = dayGroup(c.updated);
      const last = g[g.length - 1];
      if (last && last[0] === k) last[1].push(c); else g.push([k, [c]]);
    }
    return g;
  }, [convs, histQ]);

  const toggleFilters = () => { if (desk) setPop((p) => !p); else setSheet({ name: "filters", pos: "medium" }); };
  const setSheetPos = (p: SheetPos) => setSheet((s) => (s ? { ...s, pos: p } : s));
  const fDirty = !isDefaultFilters(filters);

  // ---------------------------------------------------------- qismlar
  const composer = (
    <form className="composer glass" onSubmit={(e) => { e.preventDefault(); if (busy) stop(); else ask(q); }}>
      <button type="button" className="cbtn press" data-filters onClick={toggleFilters} aria-label="Filtrlar">
        <Icon name="filter" />{fDirty && <span className="fdot" />}
      </button>
      <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" enterKeyHint="send"
        placeholder={PLACEHOLDER} aria-label="Savol" maxLength={1000} />
      <button className="send press" type="submit" aria-label={busy ? "Toʻxtatish" : "Yuborish"}>
        <Icon name="up" className="i up" />
        <svg className="i stop" viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2.5" /></svg>
      </button>
    </form>
  );
  const legal = <p className="legal">Bu yuridik maslahat emas. Rasmiy matn: <a href="https://lex.uz" target="_blank" rel="noopener noreferrer">lex.uz</a></p>;
  const nDocs = fmtNum(stats?.documents, "1 618"), nChunks = fmtNum(stats?.chunks, "39 961"), bDate = stats?.base_date || "31.10.2026";

  const cards = (pre: "d" | "m") => {
    if (!panel) return null;
    if (!panel.sources.length) {
      return panel.status === "searching" || panel.status === "writing" ? <SkeletonCards />
        : <div className="cards-empty">Bu savol uchun manba yoʻq.</div>;
    }
    return panel.sources.map((s) => (
      <div className="card-wrap" key={`${panel.id}-${s.n}`} data-n={s.n} style={{ display: "contents" }}>
        <SourceCard s={s} id={`${pre}-${s.n}`} hl={hl?.turn === panel.id && hl.n === s.n} />
      </div>
    ));
  };
  const panelTitle = <>Manbalar <small className="num">{panel?.sources.length || ""}</small></>;
  const panelSub = panel?.status === "notfound" && panel.sources.length
    ? <p className="sh-sub">Eng yaqin moddalar — savolga toʻgʻridan-toʻgʻri mos kelmadi</p>
    : panel && conv && conv.turns.length > 1
      ? <p className="sh-sub">“{panel.q.length > 60 ? panel.q.slice(0, 58) + "…" : panel.q}”</p> : null;

  const histRows = (mobile: boolean) => groups.length === 0
    ? <div className="h-empty">{histQ ? "Hech narsa topilmadi" : "Hali suhbat yoʻq. Birinchi savolni bering."}</div>
    : groups.map(([g, list]) => mobile ? (
      <div key={g}>
        <div className="grp-label">{g}</div>
        <div className="grp hlist">
          {list.map((c) => (
            <button key={c.id} className={`row${c.id === activeId ? " on" : ""}`} onClick={() => openConv(c.id)}>
              <span>{c.title}</span><time>{timeLabel(c.updated)}</time>
            </button>
          ))}
        </div>
      </div>
    ) : (
      <div key={g}>
        <h4>{g}</h4>
        {list.map((c) => (
          <button key={c.id} className={`hist${c.id === activeId ? " on" : ""}`} onClick={() => openConv(c.id)} title={c.title}>{c.title}</button>
        ))}
      </div>
    ));

  return (
    <>
      <div id="page">
        <div className="app">
          {/* Desktop yon panel */}
          <aside className="side glass" aria-label="Suhbatlar">
            <a className="brand" href="/" onClick={(e) => { e.preventDefault(); goHome(); }}><span className="mk" />Dalil</a>
            <button className="newchat press" onClick={goHome}><Icon name="plus" />Yangi suhbat</button>
            <label className="search"><Icon name="search" />
              <input value={histQ} onChange={(e) => setHistQ(e.target.value)} placeholder="Suhbatlardan qidirish" aria-label="Suhbatlardan qidirish" />
            </label>
            <div className="side-list">{histRows(false)}</div>
            <div className="side-foot">
              <div className="basebox num"><b>{nDocs}</b> hujjat · <b>{nChunks}</b> modda boʻlagi<br />Baza holati <b>{bDate}</b>, manba lex.uz</div>
              <div className="seg theme-seg" data-v={theme === "dark" ? 1 : 0}>
                <span className="thumb" />
                <button onClick={() => { setTheme("light"); saveTheme("light"); }}><Icon name="sun" />Yorugʻ</button>
                <button onClick={() => { setTheme("dark"); saveTheme("dark"); }}><Icon name="moon" />Qorongʻi</button>
              </div>
            </div>
          </aside>

          <main className={`main${scrolled ? " scrolled" : ""}`}>
            <header className="nav">
              <button className="cbtn glass press" onClick={() => setSheet({ name: "history", pos: "large" })} aria-label="Suhbatlar tarixi"><Icon name="menu" /></button>
              <div className="nav-title">
                <a className="brand" href="/" onClick={(e) => { e.preventDefault(); goHome(); }}><span className="mk" />Dalil</a>
                <div className="nav-q">{conv?.title}</div>
              </div>
              <div className="nav-right">
                <button className="scopechip glass press" data-filters onClick={toggleFilters}><Icon name="filter" /><span>{filtersLabel(filters)}</span></button>
                <button className="cbtn glass press mob-only" onClick={goHome} aria-label="Yangi suhbat"><Icon name="edit" /></button>
              </div>
            </header>

            <div className="scroll" ref={scrollRef} onScroll={(e) => {
              const s = e.currentTarget;
              setScrolled(s.scrollTop > 8);
              stick.current = s.scrollHeight - s.scrollTop - s.clientHeight < 140;
            }}>
              {!chat ? (
                <section className="home col">
                  <div className="hero">
                    <div className="orb-big" aria-hidden="true" />
                    <p className="hi">Assalomu alaykum</p>
                    <h1>Qonunchilik boʻyicha nima soʻramoqchisiz?</h1>
                    <div className="hero-composer">{desk && composer}</div>
                  </div>
                  <div className="sugs">
                    {SUGS.map((s) => (
                      <button key={s.q} className={`sug press${s.tall ? " tall" : ""}`} onClick={() => ask(s.q)}>
                        <span className="tag"><i><Icon name={s.icon} /></i>{s.tag}</span>
                        <span className="q">{s.q}</span>
                        {s.tall && <span className="go">Soʻrash <Icon name="arrow" /></span>}
                      </button>
                    ))}
                  </div>
                  <div className="stats num">
                    <div><b>{nDocs}</b>hujjat</div><div><b>{nChunks}</b>modda boʻlagi</div><div><b>{bDate}</b>baza holati</div>
                  </div>
                  <div className="home-legal">{legal}</div>
                </section>
              ) : (
                <section className="chat col" aria-live="polite">
                  {conv!.turns.map((t, i) => (
                    <TurnView key={t.id} turn={t} live={t.id === liveId} isLast={i === conv!.turns.length - 1} busy={busy}
                      activeN={hl?.turn === t.id ? hl.n : null} panelOn={panel?.id === t.id}
                      onCite={(n) => focusSource(t, n)} onCopy={() => copy(t)} onRetry={() => retry(t)}
                      onSources={() => { setPanelTurn(t.id); if (!desk) setSheet({ name: "sources", pos: "medium" }); }}
                      onTick={() => { if (stick.current && t.id === liveId) toBottom(); }} />
                  ))}
                </section>
              )}
            </div>

            <div className="dock">
              {(!desk || chat) && composer}
              {legal}
            </div>
          </main>

          {/* Desktop: manbalar inspektori */}
          <aside className="inspector" aria-label="Manbalar">
            <div className="grab"><div className="sh-head"><h2>{panelTitle}</h2></div>{panelSub}</div>
            <div className="sh-body" ref={deskBody}><div className="cards">{desk && cards("d")}</div></div>
          </aside>
        </div>
      </div>

      <div className="scrim" onClick={closeAll} />

      {/* Mobil varaqlar */}
      <Sheet id="sh-sources" className="sources-sheet" label="Manbalar" title={panelTitle} sub={panelSub}
        pos={sheet?.name === "sources" ? sheet.pos : "closed"} onPos={setSheetPos} bodyRef={mobBody}>
        <div className="cards">{!desk && cards("m")}</div>
      </Sheet>
      <Sheet id="sh-filters" label="Filtrlar" title="Qidiruv filtrlari"
        pos={sheet?.name === "filters" ? sheet.pos : "closed"} onPos={setSheetPos}>
        <FilterForm f={filters} onChange={setFilters} onClose={closeAll} />
      </Sheet>
      <Sheet id="sh-history" label="Suhbatlar" title="Suhbatlar"
        pos={sheet?.name === "history" ? sheet.pos : "closed"} onPos={setSheetPos}>
        <label className="search"><Icon name="search" />
          <input value={histQ} onChange={(e) => setHistQ(e.target.value)} placeholder="Qidirish" aria-label="Suhbatlardan qidirish" />
        </label>
        {histRows(true)}
        <button className="primary press" onClick={() => { const t = theme === "dark" ? "light" : "dark"; setTheme(t); saveTheme(t); }}>
          {theme === "dark" ? "Yorugʻ rejimga oʻtish" : "Qorongʻi rejimga oʻtish"}
        </button>
        {convs.length > 0 && <button className="linkbtn" onClick={clearHistory}>Tarixni tozalash</button>}
        <p className="legal" style={{ marginTop: 18 }}>{nDocs} hujjat · {nChunks} modda boʻlagi · baza holati {bDate}</p>
      </Sheet>

      {/* Desktop filtr popover */}
      <div className="pop glass" id="pop" role="dialog" aria-label="Filtrlar">
        <h3>Qidiruv filtrlari</h3>
        <FilterForm f={filters} onChange={setFilters} onClose={() => setPop(false)} />
      </div>

      <div className={`hud glass${hud ? " show" : ""}`} role="status"><Icon name="check" /><span>{hud}</span></div>
    </>
  );
}
