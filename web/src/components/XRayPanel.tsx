/* "Ichini ko'rish" (X-ray): bitta javob uchun RAG ichi - savolni qayta ishlash, qidiruv (dense / BM25 / RRF),
   LLM'ga yuborilgan so'rov, vaqtlar va ishonch tekshiruvi. Ma'lumot serverdagi rag.XRay'dan, qo'shimcha LLM so'rovisiz. */
import { useState, type ReactNode } from "react";
import { Icon } from "../icons";
import type { Turn, XRay, XrItem, XrSearch } from "../types";
import { dec, ScoreBar } from "./charts";

const LANG_UI: Record<string, string> = { uz: "oʻzbekcha (lotin)", uz_cyr: "oʻzbekcha (kirill)", ru: "ruscha" };
const PROVIDER: Record<string, string> = { gemini: "Gemini", openai: "OpenAI", claude: "Claude", anthropic: "Claude" };
const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2).replace(".", ",")} s` : `${Math.round(ms)} ms`);
const nf = (n: number) => n.toLocaleString("fr-FR").replace(/ | /g, " ");

async function copyText(t: string) {
  try { await navigator.clipboard.writeText(t); } catch {
    const ta = document.createElement("textarea");
    ta.value = t; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
}

function Sec({ id, title, icon, meta, children, open = true }: { id: string; title: string; icon: ReactNode; meta?: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details className="xr-sec" open={open} data-sec={id}>
      <summary><span className="xr-n">{icon}</span><span className="xr-t">{title}</span>{meta && <span className="xr-meta num">{meta}</span>}<Icon name="down" className="i chev" /></summary>
      <div className="xr-body">{children}</div>
    </details>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return <div className="xr-row"><span className="xr-k">{k}</span><span className="xr-v">{children}</span></div>;
}

function Label({ x, id, n }: { x: XRay; id: string; n?: number }) {
  const l = x.labels[id];
  return (
    <span className="xr-lab" title={l ? `${l.doc} · ${l.art}-modda ${l.title}` : id}>
      {n !== undefined && <b className="xr-cn">{n}</b>}
      <span className="xr-art">{l?.art ? `${l.art}-m.` : "—"}</span>
      <span className="xr-doc">{l?.doc || id}</span>
    </span>
  );
}

function Move({ it }: { it: XrItem }) {
  if (!it.rank_dense) return <span className="mv new" title="Faqat BM25 topdi">yangi</span>;
  const d = it.rank_dense - it.rank;
  if (d === 0) return <span className="mv eq" title={`Dense'da ham ${it.rank_dense}-oʻrin`}>=</span>;
  return <span className={`mv ${d > 0 ? "up" : "down"}`} title={`Dense'da ${it.rank_dense}-oʻrin edi`}>{d > 0 ? "↑" : "↓"}{Math.abs(d)}</span>;
}

const VIA: Record<string, string> = { both: "D+B", dense: "D", bm25: "B" };

function SearchView({ x, s, finalN }: { x: XRay; s: XrSearch; finalN: Map<string, number> }) {
  const bmMax = Math.max(1e-9, ...s.bm25.map((b) => b.score || 0));
  const f = s.filters;
  return (
    <>
      <div className="xr-chips num">
        <span>W<sub>dense</sub> {dec(s.params.w_dense, 2)}</span>
        <span>W<sub>BM25</sub> {dec(s.params.w_bm25, 3)}{s.params.w_bm25 !== s.params.w_bm25_default ? " (ruscha)" : ""}</span>
        <span>RRF k={s.params.rrf_k}</span>
        <span>har usuldan {s.params.n_each} ta</span>
        <span>{f.only_active ? "faqat amaldagi" : "barcha holat"}{f.no_amending ? " · oʻzg. qonunlarsiz" : ""}{f.doc_types ? ` · ${f.doc_types.join(", ")}` : ""}</span>
      </div>
      {s.q_dense !== s.q_bm25 && (
        <div className="xr-q2"><Row k="Dense matni">{s.q_dense}</Row><Row k="BM25 matni">{s.q_bm25}</Row></div>
      )}
      <div className="xr-tokens" aria-label="BM25 soʻzlari (7 harfli oʻzak)">
        {s.bm25_tokens.map((t, i) => <code key={i}>{t}</code>)}
      </div>
      <div className="xr-lists">
        <div className="xr-list">
          <h5><i className="sw-dense" />Dense · bge-m3 <small className="num">{s.counts.dense} nomzod · cosine</small></h5>
          <ol>
            {s.dense.map((d) => (
              <li key={d.chunk_id} className={finalN.has(d.chunk_id) ? "in" : ""}>
                <span className="rk num">{d.rank}</span><Label x={x} id={d.chunk_id} n={finalN.get(d.chunk_id)} />
                <ScoreBar v={d.cosine} min={0.4} max={0.8} tone="dense" /><span className="sc num">{dec(d.cosine)}</span>
              </li>
            ))}
          </ol>
        </div>
        <div className="xr-list">
          <h5><i className="sw-bm25 dashed" />BM25 <small className="num">{s.counts.bm25} nomzod · ball</small></h5>
          {s.bm25.length ? (
            <ol>
              {s.bm25.map((d) => (
                <li key={d.chunk_id} className={finalN.has(d.chunk_id) ? "in" : ""}>
                  <span className="rk num">{d.rank}</span><Label x={x} id={d.chunk_id} n={finalN.get(d.chunk_id)} />
                  <ScoreBar v={d.score} max={bmMax} tone="bm25" /><span className="sc num">{dec(d.score, 1)}</span>
                </li>
              ))}
            </ol>
          ) : <p className="xr-empty">BM25 hech narsa topmadi</p>}
        </div>
      </div>
      <div className="xr-list fused">
        <h5><i className="sw-hybrid" />RRF birlashma <small className="num">{s.counts.fused} → {s.fused.length} ta</small></h5>
        <ol>
          {s.fused.map((d) => (
            <li key={d.chunk_id} className={finalN.has(d.chunk_id) ? "in" : ""}>
              <span className="rk num">{d.rank}</span><Label x={x} id={d.chunk_id} n={finalN.get(d.chunk_id)} />
              <span className={`via v-${d.via}`} title={d.via === "both" ? "Ikkala usul topdi" : d.via === "dense" ? "Faqat dense topdi" : "Faqat BM25 topdi"}>{VIA[d.via || "dense"]}</span>
              <Move it={d} />
              <span className="sc num" title="RRF ball">{dec(d.score, 4)}</span>
            </li>
          ))}
        </ol>
        <p className="xr-note">RRF ball = W<sub>dense</sub>/(k + dense oʻrni) + W<sub>BM25</sub>/(k + BM25 oʻrni). ↑↓ — dense roʻyxatidagi oʻrniga nisbatan.</p>
      </div>
    </>
  );
}

function Gauge({ thr, best }: { thr: number; best: number | null }) {
  const lo = 0.3, hi = 0.85;
  const p = (v: number) => `${((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="gauge" role="img" aria-label={`Eng yaqin moslik ${dec(best)} , chegara ${dec(thr, 2)}`}>
      <div className="g-track"><span className="g-reject" style={{ width: p(thr) }} /><span className="g-thr" style={{ left: p(thr) }} />
        {best !== null && <span className={`g-best${best < thr ? " low" : ""}`} style={{ left: p(best) }} />}</div>
      <div className="g-ax num"><span>{dec(lo, 1)}</span><span>{dec(hi, 2)}</span></div>
    </div>
  );
}

function Waterfall({ x, turnMs }: { x: XRay; turnMs?: number }) {
  type R = { label: string; start: number; ms: number; tone: string; sub?: string };
  const rows: R[] = x.timeline.map((s) => ({
    label: s.label, start: s.start, ms: s.ms, sub: s.search !== undefined && x.searches.length > 1 ? (s.search ? `${s.search}-qism` : "toʻliq savol") : undefined,
    tone: s.key === "embed" || s.key === "dense" ? "dense" : s.key === "bm25" ? "bm25" : s.key === "rrf" || s.key === "fuse" ? "hybrid" : "muted",
  }));
  const l = x.llm;
  if (l?.start != null && l.first_token != null) rows.push({ label: "LLM: birinchi token", start: l.start, ms: l.first_token - l.start, tone: "llm" });
  if (l?.first_token != null && l.end != null) rows.push({ label: "LLM: javob oqimi", start: l.first_token, ms: l.end - l.first_token, tone: "llm2" });
  const total = Math.max(x.total_ms, l?.end || 0, ...rows.map((r) => r.start + r.ms), 1);
  return (
    <div className="wf">
      {rows.map((r, i) => (
        <div className="wf-row" key={i}>
          <span className="wf-l">{r.label}{r.sub && <small> · {r.sub}</small>}</span>
          <span className="wf-track"><i className={`wf-bar t-${r.tone}`} style={{ left: `${(r.start / total) * 100}%`, width: `max(3px, ${(r.ms / total) * 100}%)`, animationDelay: `${i * 35}ms` }} /></span>
          <span className="wf-ms num">{fmtMs(r.ms)}</span>
        </div>
      ))}
      <div className="wf-row tot">
        <span className="wf-l">Umumiy</span>
        <span className="wf-track"><i className="wf-bar t-total" style={{ left: 0, width: "100%" }} /></span>
        <span className="wf-ms num">{fmtMs(total)}</span>
      </div>
      <div className="wf-ax num"><span>0</span><span>{fmtMs(total / 2)}</span><span>{fmtMs(total)}</span></div>
      {!l?.end && <p className="xr-note">{x.threshold.no_answer ? "LLM chaqirilmadi: mos modda topilmadi." : x.refetched ? "Qidiruv qayta bajarildi — LLM vaqtlari yoʻq (javob X-ray oʻchiq paytda yozilgan)." : turnMs ? "" : "LLM vaqtlari javob tugagach qoʻshiladi."}</p>}
    </div>
  );
}

function PromptBox({ title, text, tokens, onHud }: { title: string; text?: string; tokens: number; onHud: (m: string) => void }) {
  return (
    <details className="xr-prompt">
      <summary><span>{title}</span><small className="num">≈{nf(tokens)} token</small>
        {text && <button className="xr-copy press" onClick={(e) => { e.preventDefault(); copyText(text).then(() => onHud(`${title} nusxalandi`)); }} aria-label={`${title}ni nusxalash`}><Icon name="copy" /></button>}
      </summary>
      {text ? <pre>{text}</pre> : <p className="xr-empty">Soʻrov matni faqat shu sessiyada saqlanadi (tarixda token soni qoladi).</p>}
    </details>
  );
}

export function XRayPanel({ turn, loading, onLoad, onHud }: { turn: Turn | null; loading: boolean; onLoad: () => void; onHud: (m: string) => void }) {
  const [si, setSi] = useState(0);
  if (!turn) return <div className="cards-empty">Savol bering — bu yerda javob qanday topilgani koʻrinadi.</div>;
  const x = turn.xray;
  if (!x) {
    const pending = turn.status === "searching";
    return (
      <div className="xr-intro">
        <span className="xr-orb"><Icon name="xray" /></span>
        <h4>{pending ? "Qidiruv ichi tayyorlanmoqda…" : "Bu javobning ichini koʻrish"}</h4>
        <p>Savol qanday tahlil qilingani, dense va BM25 qidiruvi nima topgani, RRF ularni qanday birlashtirgani, LLM’ga qanday soʻrov ketgani va har bosqich vaqti.
          {!pending && " Javob X-ray oʻchiq paytda yozilgan: qidiruv qayta bajariladi (AI soʻrovisiz)."}</p>
        {!pending && <button className="primary press" onClick={onLoad} disabled={loading}>{loading ? "Hisoblanmoqda…" : "Ichini hisoblash"}</button>}
      </div>
    );
  }
  const a = x.analysis;
  const s = x.searches[Math.min(si, Math.max(0, x.searches.length - 1))];
  const finalN = new Map(x.final.map((f) => [f.chunk_id, f.n!]));
  const th = x.threshold;
  const llm = x.llm;
  const model = llm?.model || turn.model || null;
  const trust = typeof turn.trust === "object" ? turn.trust : null;
  const totalMs = Math.max(x.total_ms, llm?.end || 0);
  return (
    <div className="xr" key={turn.id}>
      <div className="xr-sum num">
        <span><b>{x.searches.length}</b> qidiruv</span><span><b>{x.final.length}</b> manba</span>
        <span><b>{fmtMs(totalMs)}</b></span>{x.prompt && <span><b>{nf(x.prompt.tokens.total)}</b> token</span>}
      </div>
      {x.refetched && <p className="xr-warn">X-ray oʻchiq paytda berilgan savol: qidiruv joriy filtrlar bilan qayta bajarildi, natija javobdagidan farq qilishi mumkin.</p>}

      <Sec id="q" title="Savolni qayta ishlash" icon="1">
        <Row k="Asl savol">{x.question}</Row>
        <Row k="Javob tili">{LANG_UI[a.lang]} {a.forced ? <em>(sozlamada tanlangan; savol tili: {LANG_UI[a.detected]})</em> : <em>(avtomatik aniqlandi)</em>}</Row>
        <Row k="Yozuv">{a.script}</Row>
        {a.script === "kirill" && <Row k="Lotinga oʻgirildi">{a.latin}</Row>}
        {a.reuse ? <Row k="Qidiruv">qayta qidiruvsiz — oʻsha manbalar (sodda rejim)</Row> : (
          <Row k="Boʻlaklash">{a.parts.length ? (
            <ol className="xr-parts">{a.parts.map((p, i) => <li key={i}>{p}</li>)}</ol>
          ) : <>boʻlinmadi — oddiy savol <em>({a.planner})</em></>}</Row>
        )}
      </Sec>

      {x.searches.length > 0 && (
        <Sec id="s" title="Qidiruv" icon="2" meta={`${fmtMs(x.searches.reduce((t, v) => t + v.ms, 0))}`}>
          {x.searches.length > 1 && (
            <div className="xr-tabs" role="tablist">
              {x.searches.map((v, i) => (
                <button key={i} role="tab" aria-selected={i === si} className={i === si ? "on" : ""} onClick={() => setSi(i)} title={v.query}>
                  {i === 0 ? "Toʻliq savol" : `${i}-qism`}
                </button>
              ))}
            </div>
          )}
          {x.searches.length > 1 && <p className="xr-qline">«{s.query}»</p>}
          <SearchView x={x} s={s} finalN={finalN} />
          {x.fusion && (
            <div className="xr-fusion">
              <h5>Qismlar birlashtirildi <small className="num">{x.fusion.before} → {x.fusion.after} ta, takrorlarsiz</small></h5>
              <ol>
                {x.final.map((f) => (
                  <li key={f.chunk_id}><Label x={x} id={f.chunk_id} n={f.n} />
                    <span className="xr-from">{(x.fusion!.from[f.chunk_id] || []).map((i) => <i key={i}>{i === 0 ? "T" : i}</i>)}</span>
                  </li>
                ))}
              </ol>
              <p className="xr-note">T — toʻliq savol, 1, 2 — qismlar. {x.fusion.method}.</p>
            </div>
          )}
          <div className="xr-thr">
            <h5>“Topilmadi” chegarasi</h5>
            <Gauge thr={th.no_answer_cos} best={th.best_cos} />
            <p className="num">Eng yaqin moslik <b>{dec(th.best_cos)}</b> {th.best_cos !== null && th.best_cos >= th.no_answer_cos ? "≥" : "<"} NO_ANSWER_COS <b>{dec(th.no_answer_cos, 2)}</b> → {th.no_answer ? "LLM chaqirilmaydi, “topilmadi”" : "LLM chaqiriladi"}</p>
          </div>
        </Sec>
      )}

      <Sec id="p" title="LLM’ga yuborilgan soʻrov" icon="3" meta={x.prompt ? `≈${nf(x.prompt.tokens.total)} token` : "yoʻq"}>
        {x.prompt ? (
          <>
            <Row k="Provayder">{llm?.via === "own" ? `Oʻz kalitingiz · ${PROVIDER[llm.provider || ""] || llm.provider} (brauzerdan)` : llm?.via === "server" ? `Server kaliti · ${PROVIDER[llm.provider || ""] || llm.provider || "—"}` : "—"}</Row>
            <Row k="Model">{model || (turn.status === "writing" ? "javob yozilmoqda…" : "—")}</Row>
            <Row k="Token (taxminan)"><span className="num">system {nf(x.prompt.tokens.system)} · user {nf(x.prompt.tokens.user)} · jami {nf(x.prompt.tokens.total)}</span> <em>({x.prompt.tokens.method}; LLM tokenizatori biroz farq qiladi)</em></Row>
            <PromptBox title="System prompt" text={x.prompt.system} tokens={x.prompt.tokens.system} onHud={onHud} />
            <PromptBox title="User prompt (manbalar + savol)" text={x.prompt.user} tokens={x.prompt.tokens.user} onHud={onHud} />
          </>
        ) : <p className="xr-empty">LLM’ga soʻrov yuborilmadi: {th.no_answer ? "mos modda topilmadi (chegara pastda)." : "manba yoʻq."}</p>}
      </Sec>

      <Sec id="t" title="Vaqtlar" icon="4" meta={fmtMs(totalMs)}>
        <Waterfall x={x} turnMs={turn.ms} />
      </Sec>

      <Sec id="v" title="Ishonch tekshiruvi" icon="5" meta={trust ? `${trust.supported}/${trust.checked}` : turn.trust === "pending" ? "…" : "—"}>
        {trust ? (
          trust.claims.length ? (
            <ul className="xr-claims">
              {trust.claims.map((c, i) => (
                <li key={i} className={c.ok ? "ok" : "bad"}>
                  <span className="cl-ic"><Icon name={c.ok ? "check" : "alert"} /></span>
                  <div>
                    <p>“{turn.text.slice(c.start, c.end).replace(/\*\*/g, "").replace(/\s+/g, " ").slice(0, 170)}”</p>
                    <div className="cl-m num">
                      <span>manba {c.cites.length ? c.cites.map((n) => `[${n}]`).join("") : "— (iqtibossiz)"}</span>
                      <span>maʼno <ScoreBar v={c.cos} min={0.4} max={0.9} tone={c.ok ? "ok" : "lost"} /> {dec(c.cos, 2)}</span>
                      {c.lex !== null && c.lex !== undefined && <span>soʻzlar {Math.round(c.lex * 100)}%</span>}
                    </div>
                    {c.reasons.length > 0 && <small>{c.reasons.join("; ")}</small>}
                  </div>
                </li>
              ))}
            </ul>
          ) : <p className="xr-empty">Tekshiriladigan daʼvo yoʻq.</p>
        ) : <p className="xr-empty">{turn.trust === "pending" ? "Tekshirilmoqda…" : "Javob tugagach hisoblanadi (/api/verify, AI soʻrovisiz)."}</p>}
        <p className="xr-note">Har gap iqtibos qilingan modda bilan solishtiriladi: raqamlar, soʻzlar mosligi va bge-m3 maʼno oʻxshashligi (≥ 0,66; ruscha ≥ 0,64 yoki soʻzlar mosligi yuqori boʻlsa pastroq).</p>
      </Sec>
    </div>
  );
}
