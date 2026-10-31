/* Ulashish: matn (savol + javob + manba havolalari + sayt) va rasm-kartochka (canvas, 1080x1350, A·Anor uslubi). */
import { niceTitle, plainAnswer } from "./render";
import type { Source } from "./types";

export const SITE = "Dalil";
export const CARD_W = 1080, CARD_H = 1350;

type Item = { q: string; text: string; sources: Source[] };

/** "[2, 7]" -> "[2][7]" */
const splitCites = (t: string) => t.replace(/\[(\d+(?:\s*[,;]\s*\d+)+)\]/g, (_, g: string) => g.split(/\s*[,;]\s*/).map((n) => `[${n}]`).join(""));

/** Matnda iqtibos qilingan manbalar (javobdagi tartibda), bo'lmasa birinchilari */
export function citedSources(text: string, sources: Source[], max = 3): Source[] {
  const order: number[] = [];
  for (const m of splitCites(text).matchAll(/\[(\d+)\]/g)) if (!order.includes(+m[1])) order.push(+m[1]);
  const by = new Map(sources.map((s) => [s.n, s]));
  const out = order.map((n) => by.get(n)).filter(Boolean) as Source[];
  return (out.length ? out : sources).slice(0, max);
}

const shortDoc = (t: string) => niceTitle(t).replace(/^Oʻzbekiston Respublikasi(ning)?\s+/i, "").replace(/^./, (c) => c.toUpperCase());
export const sourceLabel = (s: Source) => `${shortDoc(s.doc_title)}${s.article_number ? `, ${s.article_number}-modda` : ""}`;

/** To'liq ulashish matni (navigator.share, nusxalash) */
export function shareText(it: Item): string {
  return `Savol: ${it.q}\n\n${plainAnswer(it.text, it.sources)}\n\n${SITE} — ${location.origin}`;
}

/** Havola orqali ulashish (t.me/share, wa.me) uchun qisqaroq matn: URL uzunligi cheklangan */
export function shortShareText(it: Item, max = 1400): string {
  const body = it.text.replace(/\*\*/g, "").replace(/^#{1,6}\s+/gm, "").replace(/^\s*[*•-]\s+/gm, "• ").trim();
  const cut = body.length > max ? body.slice(0, body.lastIndexOf(" ", max)) + "…" : body;
  const src = citedSources(it.text, it.sources).map((s) => `[${s.n}] ${sourceLabel(s)} — ${s.source_url}`).join("\n");
  return `Savol: ${it.q}\n\n${cut}${src ? `\n\nManbalar:\n${src}` : ""}\n\nBu yuridik maslahat emas. ${SITE} — ${location.origin}`;
}

export const telegramShareUrl = (it: Item) =>
  `https://t.me/share/url?url=${encodeURIComponent(location.origin)}&text=${encodeURIComponent(shortShareText(it))}`;
export const whatsappShareUrl = (it: Item) => `https://wa.me/?text=${encodeURIComponent(shortShareText(it))}`;

// ---------------------------------------------------------------- rasm-kartochka
const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, "Onest", system-ui, sans-serif';
const C = {
  bg: "#F6F4F2", ink: "#1C1517", ink2: "#463A3D", muted: "#75686C", card: "#FFFFFF", accent: "#B3233D", soft: "#FBE6E9",
  user: "#2A1D20", userInk: "#FFF3F4", line: "rgba(28,21,23,.10)",
  orb: ["#E2405A", "#FF9C86", "#FFD597", "#F4B3C1", "#A8173A", "#E2405A"],
  wash: [["#FFE9C4", 0, 0], ["#FFD9DC", 1, 0.05], ["#D5F0E3", 0.05, 1], ["#D9E8FA", 1, 0.97]] as [string, number, number][],
};

function rr(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  c.beginPath();
  c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r);
  c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r);
  c.arcTo(x, y, x + w, y, r);
  c.closePath();
}

function orb(c: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  const g = (c as CanvasRenderingContext2D & { createConicGradient?: (a: number, x: number, y: number) => CanvasGradient }).createConicGradient
    ? c.createConicGradient(-0.6, cx, cy) : c.createRadialGradient(cx - r / 3, cy - r / 3, 1, cx, cy, r);
  C.orb.forEach((col, i) => g.addColorStop(i / (C.orb.length - 1), col));
  c.fillStyle = g;
  c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.fill();
  const hi = c.createRadialGradient(cx - r * 0.4, cy - r * 0.48, 0, cx - r * 0.4, cy - r * 0.48, r * 0.6);
  hi.addColorStop(0, "rgba(255,255,255,.9)"); hi.addColorStop(1, "rgba(255,255,255,0)");
  c.fillStyle = hi;
  c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.fill();
}

type Tok = { t: string; cite: boolean; w: number; x?: number };

/** So'zlarni qatorlarga bo'lish; [n] - alohida "tabletka" bo'lib chiziladi */
function layout(c: CanvasRenderingContext2D, text: string, maxW: number, maxLines: number, citeFont: string, font: string) {
  const toks: Tok[] = [];
  for (const raw of text.split(/[ \t]+|(?=\n)|(?<=\n)/).filter(Boolean)) {
    if (raw === "\n") { toks.push({ t: "\n", cite: false, w: -2 }); continue; } // majburiy yangi qator (ro'yxat bandi)
    const parts = raw.split(/(\[\d+\])/).filter(Boolean);
    for (const p of parts) {
      const cite = /^\[\d+\]$/.test(p);
      c.font = cite ? citeFont : font;
      toks.push({ t: cite ? p.slice(1, -1) : p, cite, w: cite ? c.measureText(p.slice(1, -1)).width + 22 : c.measureText(p).width });
    }
    toks.push({ t: " ", cite: false, w: -1 }); // so'z oralig'i
  }
  c.font = font;
  const space = c.measureText(" ").width;
  const lines: Tok[][] = [[]];
  let x = 0;
  for (const tk of toks) {
    if (tk.w === -1) { x += space; continue; }
    const line = lines[lines.length - 1];
    const brk = tk.w === -2;
    if (brk && !line.length) continue;
    if (brk || (x + tk.w > maxW && line.length)) {
      if (lines.length === maxLines) {
        // oxirgi qatorga "…" sig'ishi uchun kerak bo'lsa oxirgi so'z olib tashlanadi
        const ell = c.measureText("…").width;
        while (line.length > 1 && (line[line.length - 1].x ?? 0) + line[line.length - 1].w + ell + 6 > maxW) line.pop();
        const last = line[line.length - 1];
        line.push({ t: "…", cite: false, w: ell, x: (last.x ?? 0) + last.w + 4 });
        return { lines, cut: true };
      }
      lines.push([]);
      x = 0;
      if (brk) continue;
    }
    tk.x = x;
    lines[lines.length - 1].push(tk);
    x += tk.w + (tk.cite ? 2 : 0);
  }
  return { lines, cut: false };
}

function drawLines(c: CanvasRenderingContext2D, lines: Tok[][], x0: number, y0: number, lh: number, font: string, citeFont: string, color: string) {
  lines.forEach((line, li) => {
    const y = y0 + li * lh;
    for (const tk of line) {
      const x = x0 + (tk.x ?? 0);
      if (tk.cite) {
        c.fillStyle = C.soft;
        rr(c, x, y - lh * 0.56, tk.w, lh * 0.66, 12);
        c.fill();
        c.fillStyle = C.accent;
        c.font = citeFont;
        c.textAlign = "center";
        c.fillText(tk.t, x + tk.w / 2, y - lh * 0.1);
        c.textAlign = "left";
      } else {
        c.fillStyle = color;
        c.font = font;
        c.fillText(tk.t, x, y);
      }
    }
  });
}

function oneLine(c: CanvasRenderingContext2D, t: string, maxW: number) {
  if (c.measureText(t).width <= maxW) return t;
  let s = t;
  while (s.length > 1 && c.measureText(s + "…").width > maxW) s = s.slice(0, -1);
  return s.trimEnd() + "…";
}

/** Ulashish uchun rasm (PNG). Matnning qisqa qismi, 1-3 manba, izoh. */
export async function makeCard(it: Item): Promise<Blob> {
  const cv = document.createElement("canvas");
  cv.width = CARD_W; cv.height = CARD_H;
  const c = cv.getContext("2d")!;
  const P = 72, IW = CARD_W - P * 2;
  // fon va rangli "yuvilish"lar (ilovadagi #page::before kabi)
  c.fillStyle = C.bg; c.fillRect(0, 0, CARD_W, CARD_H);
  for (const [col, fx, fy] of C.wash) {
    const g = c.createRadialGradient(fx * CARD_W, fy * CARD_H, 0, fx * CARD_W, fy * CARD_H, CARD_W * 0.62);
    g.addColorStop(0, col); g.addColorStop(1, "rgba(246,244,242,0)");
    c.fillStyle = g; c.fillRect(0, 0, CARD_W, CARD_H);
  }
  // sarlavha
  orb(c, P + 26, 104, 26);
  c.fillStyle = C.ink; c.font = `700 46px ${FONT}`; c.textBaseline = "alphabetic";
  c.fillText(SITE, P + 66, 120);
  c.font = `500 26px ${FONT}`; c.fillStyle = C.muted; c.textAlign = "right";
  c.fillText("Qonunchilik boʻyicha savol-javob", CARD_W - P, 116);
  c.textAlign = "left";

  // savol (to'q "pufak")
  const qFont = `650 50px ${FONT}`;
  c.font = qFont;
  const ql = layout(c, it.q, IW - 96, 3, qFont, qFont).lines;
  const qH = 48 + 34 + ql.length * 62 + 40;
  let y = 172;
  c.save(); c.shadowColor = "rgba(42,29,32,.28)"; c.shadowBlur = 40; c.shadowOffsetY = 14;
  c.fillStyle = C.user; rr(c, P, y, IW, qH, 46); c.fill(); c.restore();
  c.font = `600 24px ${FONT}`; c.fillStyle = "rgba(255,243,244,.62)";
  c.fillText("SAVOL", P + 48, y + 64);
  drawLines(c, ql, P + 48, y + 64 + 62, 62, qFont, qFont, C.userInk);
  y += qH + 28;

  // javob (oq kartochka)
  const src = citedSources(it.text, it.sources);
  const footTop = CARD_H - 120;
  const srcH = src.length ? 60 + src.length * 66 : 0;
  const aMax = footTop - srcH - 36 - y;
  const aFont = `400 35px ${FONT}`, cFont = `700 24px ${FONT}`;
  // xatboshilar bitta oqimda, ro'yxat bandlari esa yangi qatordan
  const body = splitCites(it.text).replace(/\*\*/g, "").replace(/^#{1,6}\s+/gm, "").replace(/^\s*[*•-]\s+/gm, "• ")
    .replace(/\n+(?!• |\d+[.)] )/g, " ").replace(/\n+/g, "\n").trim();
  const lh = 52;
  const maxLines = Math.max(3, Math.floor((aMax - 48 - 46 - 44) / lh));
  c.font = aFont;
  const al = layout(c, body, IW - 96, maxLines, cFont, aFont).lines;
  const aH = 48 + 46 + al.length * lh + 30;
  c.save(); c.shadowColor = "rgba(80,30,40,.13)"; c.shadowBlur = 44; c.shadowOffsetY = 14;
  c.fillStyle = C.card; rr(c, P, y, IW, aH, 46); c.fill(); c.restore();
  orb(c, P + 60, y + 56, 12);
  c.font = `600 24px ${FONT}`; c.fillStyle = C.muted;
  c.fillText("JAVOB", P + 84, y + 64);
  drawLines(c, al, P + 48, y + 64 + 58, lh, aFont, cFont, C.ink);
  y += aH + 36;

  // manbalar
  if (src.length) {
    c.font = `600 24px ${FONT}`; c.fillStyle = C.muted;
    c.fillText("MANBALAR · lex.uz", P + 8, y + 22);
    y += 52;
    for (const s of src) {
      c.fillStyle = C.soft; c.beginPath(); c.arc(P + 28, y + 22, 24, 0, Math.PI * 2); c.fill();
      c.fillStyle = C.accent; c.font = `700 24px ${FONT}`; c.textAlign = "center";
      c.fillText(String(s.n), P + 28, y + 31); c.textAlign = "left";
      c.fillStyle = C.ink; c.font = `600 30px ${FONT}`;
      c.fillText(oneLine(c, sourceLabel(s), IW - 80), P + 70, y + 33);
      y += 66;
    }
  }

  // izoh
  c.fillStyle = C.line; c.fillRect(P, footTop, IW, 2);
  c.font = `500 25px ${FONT}`; c.fillStyle = C.muted;
  c.fillText("lex.uz manbasi asosida · Bu yuridik maslahat emas", P, footTop + 58);
  c.font = `650 25px ${FONT}`; c.fillStyle = C.accent; c.textAlign = "right";
  c.fillText(location.host, CARD_W - P, footTop + 58);
  c.textAlign = "left";

  return new Promise((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("toBlob"))), "image/png"));
}

export function downloadBlob(b: Blob, name = "dalil-javob.png") {
  const url = URL.createObjectURL(b);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export async function copyText(t: string) {
  try {
    await navigator.clipboard.writeText(t);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}
