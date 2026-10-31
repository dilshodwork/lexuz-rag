/* Yengil grafiklar: o'z SVG/HTML komponentlari (chart kutubxonasi kerak emas - 4 xil grafik, ~300 qator).
   Ranglar CSS o'zgaruvchilaridan (--s-*), yorug'/qorong'i rejim alohida qadamlar bilan (styles.css, "Grafiklar").
   Har grafikda hover tooltip; matnlar har doim matn rangida, rang faqat belgida. */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export type Series = { key: string; label: string; dashed?: boolean };

export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(d).replace(".", ",")}%`);
export const dec = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? "—" : v.toFixed(d).replace(".", ","));

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

type Tip = { x: number; y: number; body: ReactNode } | null;

function TipBox({ tip, w }: { tip: Tip; w: number }) {
  if (!tip) return null;
  const left = Math.min(Math.max(tip.x, 70), Math.max(70, w - 70));
  return <div className="ch-tip" style={{ left, top: tip.y }} role="status">{tip.body}</div>;
}

export function Legend({ series }: { series: Series[] }) {
  return (
    <div className="ch-legend">
      {series.map((s) => <span key={s.key}><i className={`sw-${s.key}${s.dashed ? " dashed" : ""}`} />{s.label}</span>)}
    </div>
  );
}

const ticks01 = [0, 0.25, 0.5, 0.75, 1];

/** Guruhlangan vertikal ustunlar: guruh = metrika, ustun = rejim. Qiymatlar 0..1. */
export function GroupedBars({ groups, series, height = 240, fmt = pct }: {
  groups: { label: string; values: Record<string, number>; fmt?: (v: number) => string }[]; series: Series[]; height?: number; fmt?: (v: number) => string;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const pad = { l: 34, r: 6, t: 10, b: 26 };
  const iw = Math.max(0, w - pad.l - pad.r), ih = height - pad.t - pad.b;
  const gw = iw / Math.max(1, groups.length);
  const bw = Math.max(4, Math.min(22, (gw * 0.78) / series.length - 2));
  const y = (v: number) => pad.t + ih * (1 - v);
  return (
    <div className="ch" ref={ref} onMouseLeave={() => setTip(null)}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label="Rejimlar taqqoslash">
          {ticks01.map((t) => (
            <g key={t}>
              <line className="ch-grid" x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} />
              <text className="ch-ax" x={pad.l - 6} y={y(t) + 4} textAnchor="end">{Math.round(t * 100)}</text>
            </g>
          ))}
          {groups.map((g, gi) => {
            const x0 = pad.l + gi * gw + (gw - series.length * (bw + 2)) / 2;
            return (
              <g key={g.label}>
                {series.map((s, si) => {
                  const v = g.values[s.key] ?? 0;
                  const x = x0 + si * (bw + 2);
                  const h = Math.max(1, ih * v);
                  return (
                    <g key={s.key} className="bar-g" style={{ animationDelay: `${gi * 40 + si * 25}ms` }}
                      onMouseEnter={() => setTip({ x: x + bw / 2, y: y(v) - 8, body: <><b>{g.label}</b><span><i className={`sw-${s.key}`} />{s.label}: <b>{(g.fmt || fmt)(v)}</b></span></> })}>
                      <rect className="hit" x={x - 1} y={pad.t} width={bw + 2} height={ih} />
                      <path className={`bar fill-${s.key}`} d={h < 8 ? `M${x},${y(0)} v${-h} h${bw} v${h} z`
                        : `M${x},${y(0)} v${-(h - 4)} q0,-4 4,-4 h${bw - 8} q4,0 4,4 v${h - 4} z`} />
                    </g>
                  );
                })}
                <text className="ch-ax ch-xl" x={pad.l + gi * gw + gw / 2} y={height - 8} textAnchor="middle">{g.label}</text>
              </g>
            );
          })}
          <line className="ch-base" x1={pad.l} x2={w - pad.r} y1={y(0)} y2={y(0)} />
        </svg>
      )}
      <TipBox tip={tip} w={w} />
    </div>
  );
}

/** Chiziqli grafik (bitta o'q). x - nuqtalar, har seriya bir xil uzunlikda. Hover: vertikal chiziq + hamma seriya qiymati. */
export function LineChart({ x, series, values, height = 220, yMin = 0, yMax = 1, xFmt = (v) => String(v), yFmt = pct, tickFmt, yTicks, vline, ariaLabel, labels = true }: {
  x: number[]; series: Series[]; values: Record<string, (number | null)[]>; height?: number; yMin?: number; yMax?: number;
  xFmt?: (v: number) => string; yFmt?: (v: number) => string; tickFmt?: (v: number) => string; yTicks?: number[];
  vline?: { x: number; label: string }; ariaLabel: string; labels?: boolean;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hi, setHi] = useState<number | null>(null);
  const tf = tickFmt || (yFmt === pct ? (v: number) => `${Math.round(v * 100)}%` : yFmt);
  const pad = { l: 40, r: labels ? 92 : 12, t: 12, b: 26 };
  const iw = Math.max(0, w - pad.l - pad.r), ih = height - pad.t - pad.b;
  const x0 = x[0], x1 = x[x.length - 1];
  const sx = (v: number) => pad.l + (x1 === x0 ? 0 : ((v - x0) / (x1 - x0)) * iw);
  const sy = (v: number) => pad.t + ih * (1 - (v - yMin) / (yMax - yMin));
  const ticks = yTicks || [0, 0.25, 0.5, 0.75, 1].map((t) => yMin + t * (yMax - yMin));
  // oxirgi nuqtadagi yorliqlar bir-birini bosmasligi uchun
  const ends = series.map((s) => ({ s, y: sy(values[s.key][values[s.key].length - 1] ?? yMin) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
  const move = (e: React.MouseEvent) => {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    const px = e.clientX - r.left;
    let best = 0;
    x.forEach((v, i) => { if (Math.abs(sx(v) - px) < Math.abs(sx(x[best]) - px)) best = i; });
    setHi(best);
  };
  return (
    <div className="ch" ref={ref} onMouseLeave={() => setHi(null)}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label={ariaLabel} onMouseMove={move}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="ch-grid" x1={pad.l} x2={pad.l + iw} y1={sy(t)} y2={sy(t)} />
              <text className="ch-ax" x={pad.l - 6} y={sy(t) + 4} textAnchor="end">{tf(t)}</text>
            </g>
          ))}
          {x.map((v, i) => (i % Math.ceil(x.length / 8) === 0 || i === x.length - 1) && (
            <text key={v} className="ch-ax" x={sx(v)} y={height - 8} textAnchor="middle">{xFmt(v)}</text>
          ))}
          {vline && (
            <g>
              <line className="ch-vline" x1={sx(vline.x)} x2={sx(vline.x)} y1={pad.t} y2={pad.t + ih} />
              <text className="ch-ax ch-vl" x={sx(vline.x) + 4} y={pad.t + 10}>{vline.label}</text>
            </g>
          )}
          {series.map((s) => {
            const vs = values[s.key];
            const d = vs.map((v, i) => (v === null ? "" : `${i && vs[i - 1] !== null ? "L" : "M"}${sx(x[i]).toFixed(1)},${sy(v).toFixed(1)}`)).join("");
            return (
              <g key={s.key}>
                <path className={`line stroke-${s.key}${s.dashed ? " dashed" : ""}`} d={d} pathLength={s.dashed ? undefined : 1} />
                {vs.map((v, i) => v !== null && (vs.length <= 12 || hi === i) && (
                  <circle key={i} className={`dot fill-${s.key}`} cx={sx(x[i])} cy={sy(v)} r={hi === i ? 4.5 : 3} />
                ))}
              </g>
            );
          })}
          {labels && ends.map(({ s, y }) => (
            <text key={s.key} className="ch-dl" x={pad.l + iw + 8} y={y + 4}>{s.label}</text>
          ))}
          {hi !== null && <line className="ch-cross" x1={sx(x[hi])} x2={sx(x[hi])} y1={pad.t} y2={pad.t + ih} />}
          <rect className="hit" x={pad.l} y={pad.t} width={iw} height={ih} />
        </svg>
      )}
      {hi !== null && w > 0 && (
        <TipBox w={w} tip={{
          x: sx(x[hi]), y: pad.t, body: <><b>{xFmt(x[hi])}</b>{series.map((s) => (
            <span key={s.key}><i className={`sw-${s.key}${s.dashed ? " dashed" : ""}`} />{s.label}: <b>{values[s.key][hi] === null ? "—" : yFmt(values[s.key][hi]!)}</b></span>
          ))}</>,
        }} />
      )}
    </div>
  );
}

/** Issiqlik xaritasi: qator - kesim (kategoriya/til/qiyinlik), ustun - rejim. Bitta rang (aksent), och -> to'q. */
export function Heatmap({ rows, cols, value, fmt = pct, sub }: {
  rows: { key: string; label: string; n: number }[]; cols: Series[]; value: (r: string, c: string) => number | null;
  fmt?: (v: number) => string; sub?: (r: string, c: string) => string;
}) {
  return (
    <div className="hm" role="table" style={{ gridTemplateColumns: `minmax(92px, 1.3fr) repeat(${cols.length}, minmax(52px, 1fr))` }}>
      <div className="hm-h" role="columnheader" />
      {cols.map((c) => <div key={c.key} className="hm-h" role="columnheader"><i className={`sw-${c.key}${c.dashed ? " dashed" : ""}`} />{c.label}</div>)}
      {rows.map((r, ri) => (
        <div key={r.key} className="hm-row" role="row" style={{ display: "contents" }}>
          <div className="hm-l" role="rowheader">{r.label}<small className="num">n={r.n}</small></div>
          {cols.map((c, ci) => {
            const v = value(r.key, c.key);
            return (
              <div key={c.key} className="hm-c num" role="cell" title={sub ? sub(r.key, c.key) : undefined}
                style={{ "--v": v ?? 0, animationDelay: `${ri * 30 + ci * 20}ms` } as React.CSSProperties} data-hi={v !== null && v >= 0.62 ? 1 : 0}>
                {v === null ? "—" : fmt(v)}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/** Nuqtali taqsimot: har savolning eng yaqin cosine'i va chegara chizig'i (rad etish qanday ishlashini ko'rsatadi). */
export function StripPlot({ pos, neg, thr, min = 0.4, max = 0.8 }: {
  pos: { id: string; v: number; q: string }[]; neg: { id: string; v: number; q: string }[]; thr: number; min?: number; max?: number;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const pad = { l: 12, r: 12 }, H = 110, rows = { pos: 34, neg: 74 };
  const sx = (v: number) => pad.l + ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * (w - pad.l - pad.r);
  const jitter = (id: string) => ((id.charCodeAt(1) * 7 + id.charCodeAt(2) * 13) % 11) - 5;
  const dot = (d: { id: string; v: number; q: string }, row: "pos" | "neg") => (
    <circle key={d.id} className={`sp-dot ${row}`} cx={sx(d.v)} cy={rows[row] + jitter(d.id)} r={row === "neg" ? 6 : 4.5}
      onMouseEnter={() => setTip({ x: sx(d.v), y: rows[row] - 14, body: <><b>{d.id} · {dec(d.v)}</b><span>{d.q}</span></> })} />
  );
  const ticks = [];
  for (let t = Math.ceil(min * 10) / 10; t <= max + 1e-9; t += 0.1) ticks.push(Math.round(t * 10) / 10);
  return (
    <div className="ch" ref={ref} onMouseLeave={() => setTip(null)}>
      {w > 0 && (
        <svg width={w} height={H} role="img" aria-label="Eng yaqin cosine taqsimoti">
          <rect className="sp-reject" x={pad.l} y={8} width={Math.max(0, sx(thr) - pad.l)} height={H - 34} rx={8} />
          <text className="ch-ax" x={pad.l + 6} y={22}>topilmadi zonasi</text>
          {ticks.map((t) => <text key={t} className="ch-ax" x={sx(t)} y={H - 6} textAnchor="middle">{dec(t, 1)}</text>)}
          <line className="ch-vline" x1={sx(thr)} x2={sx(thr)} y1={8} y2={H - 26} />
          <text className="ch-ax ch-vl" x={sx(thr) + 4} y={22}>chegara {dec(thr, 2)}</text>
          {pos.map((d) => dot(d, "pos"))}
          {neg.map((d) => dot(d, "neg"))}
        </svg>
      )}
      <TipBox tip={tip} w={w} />
    </div>
  );
}

/** Kichik gorizontal ball chizig'i (X-ray ro'yxatlarida) */
export function ScoreBar({ v, max = 1, min = 0, tone = "dense" }: { v: number | null | undefined; max?: number; min?: number; tone?: string }) {
  const f = v === null || v === undefined ? 0 : Math.max(0.02, Math.min(1, (v - min) / ((max - min) || 1)));
  return <span className="sbar"><i className={`fill-${tone}`} style={{ "--f": f } as React.CSSProperties} /></span>;
}
