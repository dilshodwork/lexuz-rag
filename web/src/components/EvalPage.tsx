/* /baholash: qidiruv sifati dashboardi (eval/results.json, sweep.json). LLM'siz o'lchangan raqamlar. */
import { useEffect, useMemo, useRef, useState } from "react";
import { getEval, getEvalStatus, runEval } from "../api";
import { Icon } from "../icons";
import type { EvalBlock, EvalData, EvalMode, EvalQ, EvalResults, EvalSplit } from "../types";
import { dec, GroupedBars, Heatmap, Legend, LineChart, pct, StripPlot, type Series } from "./charts";

export const MODE_SERIES: Series[] = [
  { key: "dense", label: "Dense" }, { key: "bm25", label: "BM25", dashed: true },
  { key: "hybrid", label: "Gibrid" }, { key: "hybrid_plan", label: "Gibrid + boʻlish" },
];
const MODE_LONG: Record<EvalMode, string> = { dense: "Dense (bge-m3)", bm25: "BM25", hybrid: "Gibrid (RRF)", hybrid_plan: "Gibrid + boʻlish" };
const LANG_L: Record<string, string> = { uz: "lotin", uz_cyr: "kirill", ru: "rus" };
const SLICE_L = { category: "Kategoriya", lang: "Til / yozuv", difficulty: "Qiyinlik" } as const;
const ms = (v: number) => `${Math.round(v)} ms`;
const dt = (iso: string) => { const d = new Date(iso); return isNaN(+d) ? iso : `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

/** Savol hybrid rejimda "xato"mi: gold top-5 da yo'q yoki "bazada yo'q" savol rad etilmagan */
export function isMiss(q: EvalQ, thr: number) {
  const h = q.modes.hybrid;
  if (!h) return false;
  if (!q.answerable) return (h.best_cos ?? 1) >= thr;
  const r = h.metrics?.rank;
  return !r || r > 5;
}

function RankPill({ r, none }: { r: number | null | undefined; none?: boolean }) {
  if (none) return <span className="rp na">—</span>;
  const c = !r ? "miss" : r === 1 ? "top" : r <= 5 ? "ok" : "low";
  return <span className={`rp ${c} num`} title={r ? `${r}-oʻrin` : "top-10 da yoʻq"}>{r ?? "×"}</span>;
}

function Card({ title, sub, children, actions, id, wide }: { title: string; sub?: string; children: React.ReactNode; actions?: React.ReactNode; id?: string; wide?: boolean }) {
  return (
    <section className={`ev-card${wide ? " wide" : ""}`} id={id}>
      <header><div><h3>{title}</h3>{sub && <p>{sub}</p>}</div>{actions}</header>
      {children}
    </section>
  );
}

function Seg<T extends string>({ value, opts, onChange, label }: { value: T; opts: { v: T; l: string }[]; onChange: (v: T) => void; label: string }) {
  const i = Math.max(0, opts.findIndex((o) => o.v === value));
  return (
    <div className="seg ev-seg" data-v={i} role="radiogroup" aria-label={label} style={{ gridTemplateColumns: `repeat(${opts.length}, 1fr)`, "--n": opts.length } as React.CSSProperties}>
      <span className="thumb" style={{ width: `calc((100% - 6px) / ${opts.length})`, transform: `translateX(${i * 100}%)` }} />
      {opts.map((o) => <button key={o.v} role="radio" aria-checked={o.v === value} onClick={() => onChange(o.v)}>{o.l}</button>)}
    </div>
  );
}

export function EvalPage({ onDrill, onHud }: { onDrill: (q: EvalQ, r: EvalResults) => void; onHud: (m: string) => void }) {
  const [data, setData] = useState<EvalData | null>(null);
  const [err, setErr] = useState(false);
  const [slice, setSlice] = useState<"category" | "lang" | "difficulty">("category");
  const [sliceMetric, setSliceMetric] = useState<"recall@5" | "mrr@10">("recall@5");
  const [onlyMiss, setOnlyMiss] = useState(false);
  const [lang, setLang] = useState<"all" | "uz" | "uz_cyr" | "ru">("all");
  const [split, setSplit] = useState<EvalSplit | "all">("test");
  const [barTable, setBarTable] = useState(false);
  const poll = useRef<number | null>(null);

  const load = () => getEval().then((d) => { if (d) { setData(d); setErr(false); } else setErr(true); });
  useEffect(() => { load(); return () => { if (poll.current) clearInterval(poll.current); }; }, []);
  const watch = () => {
    if (poll.current) clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      const s = await getEvalStatus();
      if (!s) return;
      setData((d) => (d ? { ...d, run: s } : d));
      if (!s.running) {
        clearInterval(poll.current!);
        poll.current = null;
        if (s.error) onHud("Baholashda xato"); else { onHud("Baholash yangilandi"); load(); }
      }
    }, 900);
  };
  useEffect(() => { if (data?.run.running && !poll.current) watch(); }, [data?.run.running]); // eslint-disable-line react-hooks/exhaustive-deps

  const rerun = async () => {
    let token: string | undefined;
    if (data?.protected) {
      token = prompt("Qayta hisoblash himoyalangan. Ruxsat kalitini (EVAL_TOKEN) kiriting:") || undefined;
      if (!token) return;
    }
    const r = await runEval(token);
    if (!r.ok) { onHud(r.message || "Boshlab boʻlmadi"); return; }
    setData((d) => (d && r.run ? { ...d, run: r.run } : d));
    watch();
  };

  const res = data?.results;
  const sw = data?.sweep;
  const thr = (res?.meta.params.NO_ANSWER_COS as number) ?? 0.48;
  const hasSplit = !!res?.by_split?.test;
  const sp: EvalSplit | "all" = hasSplit ? split : "all";
  const inSplit = (q: EvalQ) => sp === "all" || (q.split ?? "dev") === sp;
  const rows = useMemo(() => (res ? res.questions.filter((q) => inSplit(q) && (lang === "all" || q.lang === lang) && (!onlyMiss || isMiss(q, thr))) : []), [res, lang, onlyMiss, thr, sp]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err && !data) return <div className="ev"><div className="ev-empty">Baholash natijasini yuklab boʻlmadi. Server ishlayotganini tekshiring.</div></div>;
  if (!data) return <div className="ev"><div className="ev-head"><div className="sk" style={{ width: 240, height: 34 }} /></div><div className="ev-kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="kpi sk-card"><div className="sk" /><div className="sk" style={{ width: "60%" }} /></div>)}</div></div>;
  const run = data.run;
  const runBox = (
    <button className={`ev-run press${run.running ? " on" : ""}`} onClick={rerun} disabled={run.running} aria-live="polite">
      {run.running ? (
        <>
          <span className="ev-ring" style={{ "--p": run.total ? run.done / run.total : 0 } as React.CSSProperties} />
          <span>Hisoblanmoqda <b className="num">{run.done}/{run.total || "…"}</b></span>
        </>
      ) : <><Icon name="redo" /><span>Qayta hisoblash</span></>}
    </button>
  );
  if (!res) {
    return (
      <div className="ev">
        <div className="ev-head"><div><p className="ev-eyebrow">RAG sifati</p><h1>Baholash</h1></div>{runBox}</div>
        <div className="ev-empty">Hali natija yoʻq. “Qayta hisoblash” (≈1 daqiqa, AI soʻrovisiz) yoki terminalda <code>python -m lexrag eval</code>.</div>
      </div>
    );
  }

  const m = res.meta;
  const all: EvalBlock = { n_questions: m.n_questions, n_answerable: m.n_answerable, n_none: m.n_none, counts: m.counts, summary: res.summary, rejection: res.rejection, slices: res.slices };
  const B: EvalBlock = sp !== "all" ? res.by_split![sp]! : all;
  const S = B.summary;
  const modes = m.modes;
  const series = MODE_SERIES.filter((s) => modes.includes(s.key as EvalMode));
  const bv2 = data.baseline_v2;
  // "oldin": 4-bosqichdan oldingi kod shu to'plamda (baseline_v2); u bo'lmasa - 3-bosqichdagi W_BM25 = 0,6 surati
  const base = sp !== "all" && bv2 ? bv2.by_split[sp]?.summary?.hybrid : !hasSplit ? data.baseline?.summary?.hybrid : undefined;
  const baseNote = sp !== "all" && bv2 ? "4-bosqichdan oldin" : "W_BM25 = 0,6";
  const rej = B.rejection.hybrid;
  const KPI = [
    { l: "Recall@5 · gibrid", v: pct(S.hybrid["recall@5"]), d: base ? S.hybrid["recall@5"] - base["recall@5"] : null, note: base ? `oldin ${pct(base["recall@5"])} (${baseNote})` : `${B.n_answerable} savol` },
    { l: "MRR@10 · gibrid", v: dec(S.hybrid["mrr@10"]), d: base ? S.hybrid["mrr@10"] - base["mrr@10"] : null, dFmt: (x: number) => (x >= 0 ? "+" : "") + dec(x), note: base ? `oldin ${dec(base["mrr@10"])}` : `dense ${dec(S.dense?.["mrr@10"])}` },
    { l: "Rad etish aniqligi", v: rej ? pct(rej.accuracy, 0) : "—", note: rej ? `${rej.correct_reject}/${rej.n_none} “yoʻq” rad · ${rej.false_reject}/${rej.n_answerable} xato rad` : "" },
    { l: "Oʻrtacha qidiruv", v: ms(S.hybrid.avg_ms), note: `p95 ${ms(S.hybrid.p95_ms)} · CPU, LLM’siz` },
  ];
  const groups = [
    { label: "R@1", k: "recall@1" }, { label: "R@3", k: "recall@3" }, { label: "R@5", k: "recall@5" }, { label: "R@10", k: "recall@10" },
    { label: "MRR", k: "mrr@10", fmt: (v: number) => dec(v) }, { label: "nDCG", k: "ndcg@10", fmt: (v: number) => dec(v) },
  ].map((g) => ({ label: g.label, fmt: g.fmt, values: Object.fromEntries(modes.map((md) => [md, S[md][g.k]])) }));
  const sl = B.slices[slice];
  const sliceRows = Object.entries(sl).map(([k, v]) => ({ key: k, label: slice === "lang" ? LANG_L[k] || k : k, n: Object.values(v)[0].n }));
  // sweep: tanlash har doim DEV'da; tanlangan qism jadvali ko'rsatiladi (test - faqat ma'lumot uchun)
  const gKey = sp === "all" ? "all" : sp;
  const wGrid = sw?.w_bm25.grid_by_split?.[gKey] || sw?.w_bm25.grid || [];
  const cGrid = sw?.no_answer_cos.grid_by_split?.[gKey] || sw?.no_answer_cos.grid || [];
  const selOn = (sw?.selected_on || "").toUpperCase();
  const ans = data.answers;
  const tc = data.trust_cal;
  const SPLIT_L: Record<string, string> = { test: "TEST", dev: "DEV", all: "Hammasi" };
  const langCounts = (() => {
    const c: Record<string, number> = {};
    let none = 0;
    for (const q of res.questions) { if (q.answerable) c[q.lang] = (c[q.lang] || 0) + 1; else none++; }
    return `${Object.entries(c).map(([k, v]) => `${LANG_L[k] || k} ${v}`).join(", ")}, bazada yoʻq ${none}`;
  })();

  return (
    <div className="ev">
      <div className="ev-head">
        <div>
          <p className="ev-eyebrow">RAG sifati · qidiruv, LLM’siz</p>
          <h1>Baholash</h1>
          <p className="ev-meta num"><b className="ev-size">{m.n_questions} savol</b> ({langCounts}){hasSplit && <> · DEV {res.by_split!.dev?.n_questions} / TEST {res.by_split!.test?.n_questions}</>} · {dt(m.created)} · commit <code>{m.commit || "—"}</code>{m.dirty ? " +" : ""} · {m.elapsed_s ?? "—"} s</p>
        </div>
        <div className="ev-actions">{runBox}<a className="ev-link press" href="#metodika"><Icon name="docq" />Metodika</a></div>
      </div>
      {hasSplit && (
        <div className="ev-split">
          <Seg label="Qism" value={split} onChange={setSplit} opts={[{ v: "test", l: "Test" }, { v: "dev", l: "Dev" }, { v: "all", l: "Hammasi" }]} />
          <p className="num">{sp === "test" ? <><b>TEST</b> — {B.n_questions} savol, sozlashda ishlatilmagan: yakuniy raqamlar shu yerda.</>
            : sp === "dev" ? <><b>DEV</b> — {B.n_questions} savol: sweep, chegaralar va stemmer shu qismda tanlangan.</>
              : <><b>Hammasi</b> — {B.n_questions} savol (DEV + TEST).</>}</p>
        </div>
      )}
      {run.running && <div className="ev-prog" role="progressbar" aria-valuemin={0} aria-valuemax={run.total} aria-valuenow={run.done}><i style={{ width: `${run.total ? (run.done / run.total) * 100 : 3}%` }} /><span>{run.current}</span></div>}
      {run.error && <p className="ev-err">Oxirgi qayta hisoblash xatosi: {run.error}</p>}

      <div className="ev-kpis">
        {KPI.map((k, i) => (
          <div className="kpi" key={k.l} style={{ animationDelay: `${i * 60}ms` }}>
            <span className="kpi-l">{k.l}</span>
            <b className="kpi-v num">{k.v}</b>
            <span className="kpi-n num">{k.d !== null && k.d !== undefined && <em className={k.d >= 0 ? "up" : "down"}>{k.dFmt ? k.dFmt(k.d) : `${k.d >= 0 ? "+" : ""}${(k.d * 100).toFixed(1).replace(".", ",")} p.p.`}</em>}{k.note}</span>
          </div>
        ))}
      </div>

      <div className="ev-grid">
        {bv2 && hasSplit && <BeforeAfter now={res} bv2={bv2} split={sp === "dev" ? "dev" : "test"} tc={tc} />}

        <Card title="Rejimlar taqqoslash" sub="Gold moddaning birinchi k natijada boʻlishi (recall@k), oʻrni (MRR) va tartib sifati (nDCG)"
          actions={<button className={`ev-tg press${barTable ? " on" : ""}`} onClick={() => setBarTable((t) => !t)} aria-pressed={barTable}><Icon name="table" />Jadval</button>}>
          <Legend series={series} />
          {barTable ? (
            <div className="ev-tbl-wrap"><table className="ev-tbl small"><thead><tr><th>Rejim</th>{groups.map((g) => <th key={g.label}>{g.label}</th>)}<th>vaqt</th></tr></thead>
              <tbody>{modes.map((md) => <tr key={md}><td>{MODE_LONG[md]}</td>{groups.map((g) => <td key={g.label} className="num">{(g.fmt || pct)(g.values[md])}</td>)}<td className="num">{ms(S[md].avg_ms)}</td></tr>)}</tbody></table></div>
          ) : <GroupedBars groups={groups} series={series} />}
        </Card>

        <Card title="Recall@k egri chizigʻi" sub="k = 1…10: nechta natija koʻrilsa, gold modda shuncha ehtimol bilan topiladi">
          <LineChart ariaLabel="Recall@k" x={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]} series={series}
            values={Object.fromEntries(modes.map((md) => [md, S[md].recall_curve]))} xFmt={(v) => `k=${v}`} vline={{ x: 8, label: "LLM’ga 8 ta" }} />
        </Card>

        <Card title="Kesimlar" sub="Har kesimda qaysi rejim yaxshiroq ishlaydi" wide
          actions={<div className="ev-acts"><Seg label="Kesim" value={slice} onChange={setSlice} opts={(Object.keys(SLICE_L) as (keyof typeof SLICE_L)[]).map((k) => ({ v: k, l: SLICE_L[k] }))} />
            <Seg label="Metrika" value={sliceMetric} onChange={setSliceMetric} opts={[{ v: "recall@5", l: "R@5" }, { v: "mrr@10", l: "MRR" }]} /></div>}>
          <Heatmap rows={sliceRows} cols={series} value={(r, c) => sl[r]?.[c as EvalMode]?.[sliceMetric] ?? null}
            fmt={sliceMetric === "mrr@10" ? (v) => dec(v, 2) : (v) => pct(v, 0)}
            sub={(r, c) => { const x = sl[r]?.[c as EvalMode]; return x ? `${MODE_LONG[c as EvalMode]} · ${r}: R@5 ${pct(x["recall@5"])}, MRR ${dec(x["mrr@10"])}, hit@1 ${pct(x["hit@1"])} (n=${x.n})` : ""; }} />
          <p className="ev-foot">Kichik guruhlarda (n ≤ 3) bitta savol natijani 33 foiz punktga oʻzgartiradi.</p>
        </Card>

        {sw && (
          <Card title="Sweep: BM25 ogʻirligi" sub={`Gibrid, ${SPLIT_L[gKey]}: W_BM25 oʻzgarganda sifat (joriy ${dec(sw.w_bm25.current, 2)}, eng yaxshisi ${dec(sw.w_bm25.best.w_bm25, 2)}${selOn ? ` — ${selOn} boʻyicha tanlangan` : ""})`}>
            <Legend series={[{ key: "m1", label: "Recall@5" }, { key: "m2", label: "MRR@10", dashed: true }]} />
            <LineChart ariaLabel="W_BM25 sweep" x={wGrid.map((_, i) => i)} xFmt={(i) => dec(wGrid[i]?.w_bm25, 2)}
              series={[{ key: "m1", label: "Recall@5" }, { key: "m2", label: "MRR@10", dashed: true }]}
              values={{ m1: wGrid.map((r) => r["recall@5"]), m2: wGrid.map((r) => r["mrr@10"]) }}
              yFmt={(v) => dec(v, 2)} vline={{ x: wGrid.findIndex((r) => r.w_bm25 === sw.w_bm25.current), label: "joriy" }} />
            <p className="ev-foot">3-bosqichda W_BM25 = 0,6 → 0,05. 4-bosqichda (oʻzbek stemmeri bilan) DEV sweep yana 0,05 ni tanladi; endi katta ogʻirlik kamroq zarar qiladi.</p>
          </Card>
        )}
        {sw && (
          <Card title="Sweep: “topilmadi” chegarasi" sub={`NO_ANSWER_COS, ${SPLIT_L[gKey]}: rad etilgan “yoʻq” savollar va xato rad etilgan savollar ulushi (joriy ${dec(sw.no_answer_cos.current, 2)}; DEV’da xato rad ≤ 1% sharti bilan tanlanadi)`}>
            <Legend series={[{ key: "m1", label: "Toʻgʻri rad (yoʻq savollar)" }, { key: "m2", label: "Xato rad (javobi bor)", dashed: true }]} />
            <LineChart ariaLabel="NO_ANSWER_COS sweep" x={cGrid.map((r) => r.threshold)} xFmt={(v) => dec(v, 2)} labels={false}
              series={[{ key: "m1", label: "Toʻgʻri rad" }, { key: "m2", label: "Xato rad", dashed: true }]}
              values={{ m1: cGrid.map((r) => r.reject_rate), m2: cGrid.map((r) => r.false_reject_rate) }}
              vline={{ x: sw.no_answer_cos.current, label: "joriy" }} height={190} />
            <h4 className="ev-h4">Har savolning eng yaqin cosine’i</h4>
            <StripPlot thr={sw.no_answer_cos.current}
              pos={res.questions.filter((q) => inSplit(q) && q.answerable && q.modes.hybrid?.best_cos != null).map((q) => ({ id: q.id, v: q.modes.hybrid.best_cos!, q: q.question }))}
              neg={res.questions.filter((q) => inSplit(q) && !q.answerable && q.modes.hybrid?.best_cos != null).map((q) => ({ id: q.id, v: q.modes.hybrid.best_cos!, q: q.question }))} />
            <div className="ch-legend"><span><i className="sp-k pos" />javobi bazada bor</span><span><i className="sp-k neg" />bazada yoʻq</span></div>
          </Card>
        )}

        {ans && (
          <Card title="Javob sifati (5 ta savol, haqiqiy LLM)" sub={`${ans.meta.model} · ${ans.meta.llm_requests} ta soʻrov · ${dt(ans.meta.created)}`} wide>
            <div className="ev-ans">
              <div className="kpi mini"><span className="kpi-l">Faithfulness</span><b className="kpi-v num">{ans.summary.faithfulness === null ? "—" : pct(ans.summary.faithfulness, 0)}</b><span className="kpi-n">tasdiqlangan daʼvolar ulushi</span></div>
              <div className="kpi mini"><span className="kpi-l">Gold modda iqtibosda</span><b className="kpi-v num">{ans.summary.gold_cited}/{ans.summary.answered}</b><span className="kpi-n">[n] lar hammasi toʻgʻri: {ans.summary.cites_valid}/{ans.summary.answered}</span></div>
              <ul className="ev-ans-l">
                {ans.items.map((it) => (
                  <li key={it.id}><code>{it.id}</code><span>{it.question}</span>
                    {it.trust ? <b className={`lv lv-${it.trust.level}`}>{it.trust.supported}/{it.trust.checked}</b> : <em>{it.status}</em>}</li>
                ))}
              </ul>
            </div>
            <p className="ev-foot">{tc
              ? `Bu 5 ta javob 3-bosqichdagi ishonch tekshiruvi bilan baholangan. 4-bosqichda ruscha javob → oʻzbekcha manba uchun alohida chegaralar kalibrlandi (yuqoridagi “Oldin / keyin” blokida): 7 ta haqiqiy ruscha javobda “Past” ${tc.levels.ru_real.before.low} → ${tc.levels.ru_real.after.low}.`
              : "Ishonch tekshiruvi ruscha javobda maʼno oʻxshashligini pastroq baholaydi (manba oʻzbekcha): r01 javobi toʻgʻri, lekin bitta gap “asossiz” chiqqan."}</p>
          </Card>
        )}

        <Card title="Har savol" sub="Qator bosilsa — oʻsha savolning X-ray’i: gold modda qayerda, qaysi usul topdi" wide id="savollar"
          actions={<div className="ev-acts">
            <Seg label="Til" value={lang} onChange={setLang} opts={[{ v: "all", l: "Hammasi" }, { v: "uz", l: "Lotin" }, { v: "uz_cyr", l: "Kirill" }, { v: "ru", l: "Rus" }]} />
            <label className="ev-sw"><span>Faqat xatolar</span><button className={`sw${onlyMiss ? " on" : ""}`} role="switch" aria-checked={onlyMiss} aria-label="Faqat xatolar" onClick={() => setOnlyMiss((x) => !x)} /></label>
          </div>}>
          <div className="ev-tbl-wrap">
            <table className="ev-tbl">
              <thead><tr><th>ID</th><th>Savol</th><th className="hide-m">Gold</th><th className="hide-m">Kesim</th>{series.map((s) => <th key={s.key} className="c" title={s.label}><i className={`sw-${s.key}${s.dashed ? " dashed" : ""}`} />{s.key === "hybrid_plan" ? "G+B" : s.label}</th>)}</tr></thead>
              <tbody>
                {rows.map((q) => (
                  <tr key={q.id} className={isMiss(q, thr) ? "miss" : ""} tabIndex={0} onClick={() => onDrill(q, res)} onKeyDown={(e) => { if (e.key === "Enter") onDrill(q, res); }}>
                    <td className="num id">{q.id}</td>
                    <td className="q"><span>{q.question}</span><small>{LANG_L[q.lang]} · {q.category} · {q.difficulty}{sp === "all" && q.split ? ` · ${q.split.toUpperCase()}` : ""}</small></td>
                    <td className="hide-m g">{q.gold.length ? q.gold.map((g) => `${g.doc.replace(/ \(.*\)/, "")} ${g.article}`).join("; ") : <em>bazada yoʻq</em>}</td>
                    <td className="hide-m">{q.category}</td>
                    {series.map((s) => {
                      const md = q.modes[s.key as EvalMode];
                      if (!q.answerable) {
                        const c = md?.best_cos;
                        return <td key={s.key} className="c">{c == null ? <span className="rp na">—</span> : <span className={`rp ${c < thr ? "top" : "miss"} num`} title={`eng yaqin cosine ${dec(c)}`}>{c < thr ? "rad" : "×"}</span>}</td>;
                      }
                      return <td key={s.key} className="c"><RankPill r={md?.metrics?.rank} /></td>;
                    })}
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={8} className="ev-none">Bu filtr boʻyicha savol yoʻq.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="ev-foot">Raqam — gold moddaning oʻrni (1 = birinchi), × — top-10 da yoʻq. “Yoʻq” savollarda: rad — toʻgʻri rad etildi.</p>
        </Card>

        <Card title="Metodika" wide id="metodika">
          <div className="ev-method">
            <div>
              <h4>Toʻplam</h4>
              <p>{m.n_questions} ta savol: {langCounts}; {Object.keys(m.counts.category || {}).length} kategoriya. Avval modda tanlanib, matni oʻqildi, keyin savol oddiy odam tilida <b>parafraza</b> qilindi (modda matnidan koʻchirilmagan — aks holda BM25 sunʼiy yutadi); kirillning bir qismi rus klaviaturasida, lotinning bir qismi apostrofsiz. Gold — hujjat ID + modda raqami, har ishga tushishda bazada borligi tekshiriladi. Moddani tanlashda qidiruv tizimi ishlatilmagan.{hasSplit && <> <b>DEV / TEST</b>: tasodifiy, kategoriya va til boʻyicha muvozanatli; barcha sozlash faqat DEV’da, yakuniy raqamlar — TEST.</>}</p>
            </div>
            <div>
              <h4>Metrikalar</h4>
              <p><b>Recall@k</b> — gold moddalarning birinchi k natijadagi ulushi. <b>MRR@10</b> — 1 / birinchi toʻgʻri moddaning oʻrni. <b>nDCG@10</b> — bir nechta gold boʻlsa hammasining oʻrni. <b>Rad etish</b> — eng yaqin manba cosine’i NO_ANSWER_COS ({dec(thr, 2)}) dan past boʻlsa LLM chaqirilmaydi.</p>
            </div>
            <div>
              <h4>Rejimlar</h4>
              <p><b>Dense</b> — bge-m3 + ChromaDB. <b>BM25</b> — soʻz mosligi ({(m.params.tokenizer as { kind?: string } | undefined)?.kind === "stem" ? "oʻzbek stemmeri + stopwordlar; ruscha savol BM25’ga yuborilmaydi" : "7 harfli oʻzak"}). <b>Gibrid</b> — RRF: W<sub>dense</sub>/(60+oʻrin) + W<sub>BM25</sub>/(60+oʻrin), W<sub>BM25</sub> = {dec(m.params.W_BM25, 2)}. <b>Gibrid + boʻlish</b> — murakkab savol 2–3 qismga boʻlinib, natijalar birlashtiriladi. Ilovadagi funksiyalarning oʻzi chaqiriladi.</p>
            </div>
            <div>
              <h4>Cheklovlar</h4>
              <p>{hasSplit
                ? <>Yangi savollarni bitta model oilasi (Claude) yozgan — uslub bir xil boʻlishi mumkin. TEST’da {res.by_split!.test?.n_answerable} javobli savol: 1 savol ≈ {dec(100 / (res.by_split!.test?.n_answerable || 1), 2)} foiz punkt, ~3 punktdan kichik farq shovqin ichida. “Yoʻq” savollar {m.n_none} ta; chet el qonunlari haqidagi savollarni cosine bilan ajratib boʻlmaydi.</>
                : <>Savollarni bir kishi yozgan; 1 savol ≈ 2,2 foiz punkt, shuning uchun 2–3 punktlik farq shovqin ichida. “Yoʻq” savollar {m.n_none} ta.</>} Vaqt — Intel i7 CPU, model xotirada. Batafsil: <code>eval/README.md</code>.</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

type BARow = { g?: string; l: string; get: (b: EvalBlock) => number | undefined; mrr?: boolean };
const lgR5 = (lang: string, mode: EvalMode) => (b: EvalBlock) => b.slices.lang?.[lang]?.[mode]?.["recall@5"];
const BA_ROWS: BARow[] = [
  { g: "Gibrid (asosiy rejim)", l: "Recall@5", get: (b) => b.summary.hybrid?.["recall@5"] },
  { l: "Recall@1", get: (b) => b.summary.hybrid?.["recall@1"] },
  { l: "MRR@10", get: (b) => b.summary.hybrid?.["mrr@10"], mrr: true },
  { g: "BM25 yolgʻiz (stemmer)", l: "Recall@5", get: (b) => b.summary.bm25?.["recall@5"] },
  { l: "MRR@10", get: (b) => b.summary.bm25?.["mrr@10"], mrr: true },
  { g: "Kirill savollar", l: "Gibrid R@5", get: lgR5("uz_cyr", "hybrid") },
  { l: "BM25 R@5", get: lgR5("uz_cyr", "bm25") },
  { g: "Lotin savollar", l: "Gibrid R@5", get: lgR5("uz", "hybrid") },
  { g: "Rus savollar", l: "Gibrid R@5", get: lgR5("ru", "hybrid") },
];
const fmtV = (v: number | undefined, mrr?: boolean) => (v == null ? "—" : mrr ? dec(v) : pct(v));
const fmtD = (d: number, mrr?: boolean) => (Math.abs(d) < 1e-9 ? "0" : (d > 0 ? "+" : "−") + (mrr ? dec(Math.abs(d)) : `${(Math.abs(d) * 100).toFixed(1).replace(".", ",")} p.p.`));

function LvBar({ c, label }: { c: { high: number; medium: number; low: number }; label: string }) {
  const n = c.high + c.medium + c.low || 1;
  return (
    <div className="ba-lv" role="img" aria-label={`${label}: Yuqori ${c.high}, Oʻrta ${c.medium}, Past ${c.low}`}>
      <span className="ba-lv-l">{label}</span>
      <span className="ba-lv-bar">{(["high", "medium", "low"] as const).map((k) => c[k] > 0 && <i key={k} className={`lv-${k}`} style={{ flexGrow: c[k] / n }} title={`${k === "high" ? "Yuqori" : k === "medium" ? "Oʻrta" : "Past"}: ${c[k]}`} />)}</span>
      <span className="ba-lv-t num">Yuqori {c.high} · Oʻrta {c.medium} · Past {c.low}</span>
    </div>
  );
}

/** "Oldin / keyin": 4-bosqichdan oldingi kod (baseline_v2) va hozirgi kod - bir xil savollarda. Asosiy qism (TEST yoki
 *  tanlangan DEV) katta, ikkinchisi kichik yozuvda. Shkala 0-100% (MRR 0-1) - farqlar kichik bo'lsa nuqtalar yaqin. */
function BeforeAfter({ now, bv2, split, tc }: { now: EvalResults; bv2: NonNullable<EvalData["baseline_v2"]>; split: EvalSplit; tc?: EvalData["trust_cal"] }) {
  const other: EvalSplit = split === "test" ? "dev" : "test";
  const A = now.by_split?.[split], Bf = bv2.by_split[split], Ao = now.by_split?.[other], Bo = bv2.by_split[other];
  if (!A || !Bf) return null;
  const ra = A.rejection.hybrid, rb = Bf.rejection.hybrid;
  return (
    <Card title="Oldin / keyin" wide id="oldin-keyin"
      sub={`4-bosqich: kirill, BM25 (oʻzbek stemmeri) va ruscha ishonch belgisi. Oldin — 3-bosqich kodi aynan shu ${now.meta.n_questions} savolda; asosiy raqamlar ${split.toUpperCase()} (${A.n_answerable} javobli savol), ${other.toUpperCase()} — kichik yozuvda.`}>
      <div className="ch-legend"><span><i className="ba-k before" />oldin</span><span><i className="ba-k after" />keyin</span></div>
      <div className="ba" role="table" aria-label="Oldin va keyin">
        {BA_ROWS.map((r, i) => {
          const b = r.get(Bf), a = r.get(A), bo = Bo && r.get(Bo), ao = Ao && r.get(Ao);
          if (a == null || b == null) return null;
          const d = a - b;
          const lo = Math.min(a, b), hi = Math.max(a, b);
          return (
            <div className={`ba-row${r.g ? " first" : ""}`} role="row" key={i} title={`${r.g || ""} ${r.l}: ${fmtV(b, r.mrr)} → ${fmtV(a, r.mrr)}`}>
              <div className="ba-l" role="rowheader">{r.g && <b>{r.g}</b>}<span>{r.l}</span></div>
              <div className="ba-track" aria-hidden="true">
                <span className="ba-seg" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />
                <span className="ba-dot before" style={{ left: `${b * 100}%` }} />
                <span className="ba-dot after" style={{ left: `${a * 100}%` }} />
              </div>
              <div className="ba-v num" role="cell">
                <span>{fmtV(b, r.mrr)} → <b>{fmtV(a, r.mrr)}</b></span>
                <em className={Math.abs(d) < 1e-9 ? "eq" : d > 0 ? "up" : "down"}>{fmtD(d, r.mrr)}</em>
                {bo != null && ao != null && <small>{other.toUpperCase()}: {fmtV(bo, r.mrr)} → {fmtV(ao, r.mrr)}</small>}
              </div>
            </div>
          );
        })}
      </div>
      <div className="ba-foot">
        {ra && rb && <p className="num"><b>“Bazada yoʻq” savollar:</b> toʻgʻri rad {rb.correct_reject}/{rb.n_none} → {ra.correct_reject}/{ra.n_none}, xato rad {rb.false_reject}/{rb.n_answerable} → {ra.false_reject}/{ra.n_answerable} (NO_ANSWER_COS {dec(now.meta.params.NO_ANSWER_COS, 2)} — DEV’da qayta tekshirildi, oʻzgarmadi).</p>}
        {tc && (
          <div className="ba-trust">
            <h4 className="ev-h4">Ishonch belgisi: ruscha javob → oʻzbekcha manba (7 ta haqiqiy LLM javobi, qoʻlda tekshirilgan — hammasi toʻgʻri)</h4>
            <LvBar c={tc.levels.ru_real.before} label="Oldin" />
            <LvBar c={tc.levels.ru_real.after} label="Keyin" />
            <p className="ev-foot num">Toʻgʻri ruscha daʼvolar tasdiqlandi {tc.ru_true.before[0]}/{tc.ru_true.before[1]} → <b>{tc.ru_true.after[0]}/{tc.ru_true.after[1]}</b>; ataylab yozilgan yolgʻon daʼvolar oʻtib ketdi {tc.ru_false.before[0]}/{tc.ru_false.before[1]} → {tc.ru_false.after[0]}/{tc.ru_false.after[1]} (oʻzbekcha tekshiruv ularning oʻzbekcha variantidan {tc.uz_false[0]}/{tc.uz_false[1]} oʻtkazadi — endi teng qatʼiylik). Chegara {dec(tc.params.old.ok, 2)} → {dec(tc.params.new.ok, 2)}, sonli daʼvo {dec(tc.params.new.num, 2)}. Oʻzbekcha javoblar: oʻzgarmadi.</p>
          </div>
        )}
      </div>
    </Card>
  );
}

/** Bitta savol drilldown'i (App uni desktopda dialog, mobilda varaq ichida ko'rsatadi) */
export function EvalDrill({ q, r }: { q: EvalQ; r: EvalResults }) {
  const thr = r.meta.params.NO_ANSWER_COS as number;
  const modes = r.meta.modes;
  return (
    <div className="drill">
      <p className="dr-q">{q.question}</p>
      <div className="dr-tags"><span>{LANG_L[q.lang]}</span><span>{q.category}</span><span>{q.difficulty}</span>{q.parts.length > 0 && <span>{q.parts.length} qismga boʻlindi</span>}</div>
      <div className="grp-label">Gold modda</div>
      <div className="dr-gold">
        {q.gold.length ? q.gold.map((g) => <div key={g.doc_id + g.article}><b>{g.article}-modda</b> · {g.doc}</div>) : <div><b>Bazada yoʻq</b> — toʻgʻri natija: “topilmadi”</div>}
      </div>
      {q.answerable ? (
        <div className="dr-ranks">
          {modes.map((md) => {
            const rk = q.modes[md]?.metrics?.rank;
            return <div key={md} className="dr-rank"><i className={`sw-${md}${md === "bm25" ? " dashed" : ""}`} /><span>{MODE_LONG[md]}</span><RankPill r={rk} /></div>;
          })}
          <p className="dr-note num">Nomzodlar roʻyxatida (40 tadan): dense <b>{q.gold_rank_dense ?? ">40"}</b>-oʻrin, BM25 <b>{q.gold_rank_bm25 ?? ">40"}</b>-oʻrin.
            {q.gold_rank_dense && !q.gold_rank_bm25 ? " Faqat dense topdi." : !q.gold_rank_dense && q.gold_rank_bm25 ? " Faqat BM25 topdi." : !q.gold_rank_dense ? " Ikkala usul ham topmadi." : " Ikkala usul ham topdi."}</p>
        </div>
      ) : (
        <p className="dr-note num">Eng yaqin cosine <b>{dec(q.modes.hybrid?.best_cos)}</b> {(q.modes.hybrid?.best_cos ?? 1) < thr ? "<" : "≥"} chegara {dec(thr, 2)} → {(q.modes.hybrid?.best_cos ?? 1) < thr ? "toʻgʻri rad etildi" : "rad etilmadi (LLM’ga ketadi; LLM oʻzi “manbada yoʻq” deyishi kerak)"}.</p>
      )}
      {(["hybrid", "dense", "bm25", "hybrid_plan"] as EvalMode[]).filter((md) => modes.includes(md) && (md !== "hybrid_plan" || q.parts.length)).map((md) => (
        <div key={md}>
          <div className="grp-label"><i className={`sw-${md}${md === "bm25" ? " dashed" : ""}`} /> {MODE_LONG[md]} · top-5 <span className="num">{q.modes[md].ms.toFixed(0)} ms</span></div>
          <ol className="dr-top">
            {q.modes[md].top.map((t) => (
              <li key={t.chunk_id + t.rank} className={t.gold ? "gold" : ""}>
                <span className="rk num">{t.rank}</span>
                <span className="dr-t"><b>{t.art ? `${t.art}-m.` : "—"}</b> {t.doc}<small>{t.title}</small></span>
                <span className="dr-r num" title="dense / BM25 roʻyxatidagi oʻrni">D{t.rank_dense ?? "–"} · B{t.rank_bm25 ?? "–"}</span>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}
