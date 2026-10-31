/* /baholash: qidiruv sifati dashboardi (eval/results.json, sweep.json). LLM'siz o'lchangan raqamlar. */
import { useEffect, useMemo, useRef, useState } from "react";
import { getEval, getEvalStatus, runEval } from "../api";
import { Icon } from "../icons";
import type { EvalData, EvalMode, EvalQ, EvalResults } from "../types";
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
  const rows = useMemo(() => (res ? res.questions.filter((q) => (lang === "all" || q.lang === lang) && (!onlyMiss || isMiss(q, thr))) : []), [res, lang, onlyMiss, thr]);

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

  const m = res.meta, S = res.summary;
  const modes = m.modes;
  const series = MODE_SERIES.filter((s) => modes.includes(s.key as EvalMode));
  const base = data.baseline?.summary?.hybrid;
  const rej = res.rejection.hybrid;
  const KPI = [
    { l: "Recall@5 · gibrid", v: pct(S.hybrid["recall@5"]), d: base ? S.hybrid["recall@5"] - base["recall@5"] : null, note: base ? `oldin ${pct(base["recall@5"])} (W_BM25 = 0,6)` : `${m.n_answerable} savol` },
    { l: "MRR@10 · gibrid", v: dec(S.hybrid["mrr@10"]), d: base ? S.hybrid["mrr@10"] - base["mrr@10"] : null, dFmt: (x: number) => (x >= 0 ? "+" : "") + dec(x), note: `dense ${dec(S.dense?.["mrr@10"])}` },
    { l: "Rad etish aniqligi", v: rej ? pct(rej.accuracy, 0) : "—", note: rej ? `${rej.correct_reject}/${rej.n_none} “yoʻq” rad · ${rej.false_reject}/${rej.n_answerable} xato rad` : "" },
    { l: "Oʻrtacha qidiruv", v: ms(S.hybrid.avg_ms), note: `p95 ${ms(S.hybrid.p95_ms)} · CPU, LLM’siz` },
  ];
  const groups = [
    { label: "R@1", k: "recall@1" }, { label: "R@3", k: "recall@3" }, { label: "R@5", k: "recall@5" }, { label: "R@10", k: "recall@10" },
    { label: "MRR", k: "mrr@10", fmt: (v: number) => dec(v) }, { label: "nDCG", k: "ndcg@10", fmt: (v: number) => dec(v) },
  ].map((g) => ({ label: g.label, fmt: g.fmt, values: Object.fromEntries(modes.map((md) => [md, S[md][g.k]])) }));
  const sl = res.slices[slice];
  const sliceRows = Object.entries(sl).map(([k, v]) => ({ key: k, label: slice === "lang" ? LANG_L[k] || k : k, n: Object.values(v)[0].n }));
  const wGrid = sw?.w_bm25.grid || [];
  const cGrid = sw?.no_answer_cos.grid || [];
  const ans = data.answers;

  return (
    <div className="ev">
      <div className="ev-head">
        <div>
          <p className="ev-eyebrow">RAG sifati · qidiruv, LLM’siz</p>
          <h1>Baholash</h1>
          <p className="ev-meta num">{m.n_questions} savol ({m.n_answerable} tasi gold modda bilan, {m.n_none} tasi bazada yoʻq) · {dt(m.created)} · commit <code>{m.commit || "—"}</code>{m.dirty ? " +" : ""} · {m.elapsed_s ?? "—"} s</p>
        </div>
        <div className="ev-actions">{runBox}<a className="ev-link press" href="#metodika"><Icon name="docq" />Metodika</a></div>
      </div>
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
          <Card title="Sweep: BM25 ogʻirligi" sub={`Gibrid: W_BM25 oʻzgarganda sifat (joriy ${dec(sw.w_bm25.current, 2)}, eng yaxshisi ${dec(sw.w_bm25.best.w_bm25, 2)})`}>
            <Legend series={[{ key: "m1", label: "Recall@5" }, { key: "m2", label: "MRR@10", dashed: true }]} />
            <LineChart ariaLabel="W_BM25 sweep" x={wGrid.map((_, i) => i)} xFmt={(i) => dec(wGrid[i]?.w_bm25, 2)}
              series={[{ key: "m1", label: "Recall@5" }, { key: "m2", label: "MRR@10", dashed: true }]}
              values={{ m1: wGrid.map((r) => r["recall@5"]), m2: wGrid.map((r) => r["mrr@10"]) }}
              yFmt={(v) => dec(v, 2)} vline={{ x: wGrid.findIndex((r) => r.w_bm25 === sw.w_bm25.current), label: "joriy" }} />
            <p className="ev-foot">Oldin W_BM25 = 0,6 edi: BM25 umumiy soʻzlar boʻyicha shovqin berib, dense topgan moddani pastga surardi.</p>
          </Card>
        )}
        {sw && (
          <Card title="Sweep: “topilmadi” chegarasi" sub={`NO_ANSWER_COS: rad etilgan “yoʻq” savollar va xato rad etilgan savollar ulushi (joriy ${dec(sw.no_answer_cos.current, 2)})`}>
            <Legend series={[{ key: "m1", label: "Toʻgʻri rad (yoʻq savollar)" }, { key: "m2", label: "Xato rad (javobi bor)", dashed: true }]} />
            <LineChart ariaLabel="NO_ANSWER_COS sweep" x={cGrid.map((r) => r.threshold)} xFmt={(v) => dec(v, 2)} labels={false}
              series={[{ key: "m1", label: "Toʻgʻri rad" }, { key: "m2", label: "Xato rad", dashed: true }]}
              values={{ m1: cGrid.map((r) => r.reject_rate), m2: cGrid.map((r) => r.false_reject_rate) }}
              vline={{ x: sw.no_answer_cos.current, label: "joriy" }} height={190} />
            <h4 className="ev-h4">Har savolning eng yaqin cosine’i</h4>
            <StripPlot thr={sw.no_answer_cos.current}
              pos={res.questions.filter((q) => q.answerable && q.modes.hybrid?.best_cos != null).map((q) => ({ id: q.id, v: q.modes.hybrid.best_cos!, q: q.question }))}
              neg={res.questions.filter((q) => !q.answerable && q.modes.hybrid?.best_cos != null).map((q) => ({ id: q.id, v: q.modes.hybrid.best_cos!, q: q.question }))} />
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
            <p className="ev-foot">Ishonch tekshiruvi ruscha javobda maʼno oʻxshashligini pastroq baholaydi (manba oʻzbekcha): r01 javobi toʻgʻri, lekin bitta gap “asossiz” chiqqan.</p>
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
                    <td className="q"><span>{q.question}</span><small>{LANG_L[q.lang]} · {q.category} · {q.difficulty}</small></td>
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
              <p>{m.n_questions} ta savol: {Object.entries(m.counts.lang).map(([k, v]) => `${LANG_L[k] || k} ${v}`).join(", ")}; {m.n_none} tasi ataylab bazada yoʻq. Avval modda tanlanib, matni oʻqildi, keyin savol oddiy odam tilida <b>parafraza</b> qilindi (modda matnidan koʻchirilmagan — aks holda BM25 sunʼiy yutadi). Gold — hujjat ID + modda raqami, har ishga tushishda bazada borligi tekshiriladi. Moddani tanlashda qidiruv tizimi ishlatilmagan.</p>
            </div>
            <div>
              <h4>Metrikalar</h4>
              <p><b>Recall@k</b> — gold moddalarning birinchi k natijadagi ulushi. <b>MRR@10</b> — 1 / birinchi toʻgʻri moddaning oʻrni. <b>nDCG@10</b> — bir nechta gold boʻlsa hammasining oʻrni. <b>Rad etish</b> — eng yaqin manba cosine’i NO_ANSWER_COS ({dec(thr, 2)}) dan past boʻlsa LLM chaqirilmaydi.</p>
            </div>
            <div>
              <h4>Rejimlar</h4>
              <p><b>Dense</b> — bge-m3 + ChromaDB. <b>BM25</b> — soʻz mosligi (7 harfli oʻzak). <b>Gibrid</b> — RRF: W<sub>dense</sub>/(60+oʻrin) + W<sub>BM25</sub>/(60+oʻrin), W<sub>BM25</sub> = {dec(m.params.W_BM25, 2)}. <b>Gibrid + boʻlish</b> — murakkab savol 2–3 qismga boʻlinib, natijalar birlashtiriladi. Ilovadagi funksiyalarning oʻzi chaqiriladi.</p>
            </div>
            <div>
              <h4>Cheklovlar</h4>
              <p>Savollarni bir kishi yozgan; 1 savol ≈ 2,2 foiz punkt, shuning uchun 2–3 punktlik farq shovqin ichida. “Yoʻq” savollar 4 ta. Vaqt — Intel i7 CPU, model xotirada. Batafsil: <code>eval/README.md</code>.</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
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
