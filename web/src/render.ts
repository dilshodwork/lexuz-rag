/* Javob matni (LLM markdown'i) -> HTML.
   * **qalin**, "- " / "* " ro'yxat, "1. " raqamli ro'yxat, "### sarlavha"
   * [1], [1][3], [1, 2] -> bosiladigan iqtibos tugmalari (faqat mavjud manba raqamlari)
   * Har so'z indekslanadi: yangi chiqqan so'zlar .w (xiralikdan chiqish) animatsiyasini oladi.
     Animatsiya davom etayotgan so'z qayta chizilganda manfiy animation-delay bilan uzilmasdan davom etadi. */

/* XSS: LLM va manba matni HTML sifatida talqin qilinmaydi - har so'z esc() dan o'tadi, HTML'ni faqat shu fayl
   yasaydi va faqat shu teglar: p, ul, ol, li, strong, span (.w, .wk), button.cite. Atribut qiymatlari - faqat
   raqamlar (data-n, data-c, animation-delay). scripts/test_render.mjs buni tekshiradi. */
export const esc = (x: string) =>
  x.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

/** Manba havolasi: faqat https://lex.uz/... (indeksdagi qiymat buzilgan bo'lsa ham javascript: va h.k. o'tmaydi) */
export function safeLexUrl(u: string | null | undefined): string {
  return typeof u === "string" && /^https:\/\/(www\.)?lex\.uz\//i.test(u) ? u : "https://lex.uz/";
}
const ANIM_MS = 520;
const CITE = /\[(\d+(?:\s*[,;]\s*\d+)*)\]/g;

export type RenderOpts = {
  maxN: number;          // manbalar soni: [n] faqat 1..maxN bo'lsa tugma bo'ladi
  activeN?: number | null;
  times?: number[];      // so'z indeksi -> paydo bo'lgan vaqt (live oqim uchun)
  now?: number;
  marks?: { start: number; end: number; i: number }[]; // asossiz ko'ringan gaplar (ishonch tekshiruvi)
};

// gap belgisi: ochuvchi belgi U+E100+i (i - da'vo raqami), yopuvchi U+E001
const MARK_OPEN = 0xe100, MARK_CLOSE = "";
const SENT = /([-])/;

/** Belgilarni matnga joylash (oxiridan boshlab, o'rinlar siljimasin) */
function withMarks(text: string, marks: RenderOpts["marks"]) {
  if (!marks?.length) return text;
  let t = text;
  for (const m of [...marks].sort((a, b) => b.start - a.start)) {
    if (m.end > t.length || m.start >= m.end) continue;
    t = t.slice(0, m.start) + String.fromCharCode(MARK_OPEN + m.i) + t.slice(m.start, m.end) + MARK_CLOSE + t.slice(m.end);
  }
  return t;
}

export function renderAnswer(src: string, o: RenderOpts): string {
  const text = withMarks(src, o.marks);
  let idx = 0;
  let mark = -1; // hozir belgilangan gap ichidami
  const now = o.now ?? 0;
  const wrapMark = (html: string) => (mark >= 0 ? `<span class="wk" data-c="${mark}">${html}</span>` : html);
  const anim = (): string => {
    if (!o.times) return "";
    const k = idx++;
    if (o.times[k] === undefined) o.times[k] = now;
    const age = now - o.times[k];
    if (age >= ANIM_MS) return "";
    return ` style="animation-delay:-${Math.round(age)}ms"`;
  };
  const cite = (n: string) => {
    const a = anim();
    const on = o.activeN === +n ? " on" : "";
    return `<button class="cite${a ? " w" : ""}${on}" data-n="${n}" aria-label="${n}-manba"${a}>${n}</button>`;
  };
  const token = (t: string) => {
    const parts: string[] = [];
    let last = 0;
    for (const m of t.matchAll(CITE)) {
      const nums = m[1].split(/\s*[,;]\s*/);
      if (!nums.every((n) => +n >= 1 && +n <= o.maxN)) continue;
      if (m.index! > last) parts.push(word(t.slice(last, m.index)));
      nums.forEach((n) => parts.push(cite(n)));
      last = m.index! + m[0].length;
    }
    if (last < t.length) parts.push(word(t.slice(last)));
    return parts.join("");
  };
  // "[2, 7]" ichidagi bo'sh joyda bo'linmaydi (aks holda iqtibos tugmaga aylanmaydi)
  const words = (x: string) =>
    x.split(/(?<!\[[\d\s,;]*[,;])(\s+)/).map((t) => {
      if (!t) return t;
      if (/^\s+$/.test(t)) return wrapMark(t);
      // gap belgilari so'z ichida kelishi mumkin ("muddat.")
      return t.split(SENT).map((p) => {
        if (p === MARK_CLOSE) { mark = -1; return ""; }
        if (p.length === 1 && p.charCodeAt(0) >= MARK_OPEN && p.charCodeAt(0) <= MARK_OPEN + 0xff) { mark = p.charCodeAt(0) - MARK_OPEN; return ""; }
        return p ? wrapMark(token(p)) : "";
      }).join("");
    }).join("");
  const word = (w: string) => {
    const a = anim();
    return a ? `<span class="w"${a}>${esc(w)}</span>` : esc(w);
  };
  // **qalin**: juft bo'lmagan oxirgi ** (oqim davomida) ham qalin boshlanadi
  const inl = (x: string) => x.split("**").map((p, i) => (i % 2 ? `<strong>${words(p)}</strong>` : words(p))).join("");

  const out: string[] = [];
  let list: { tag: "ul" | "ol"; items: string[] } | null = null;
  const flush = () => {
    if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${i}</li>`).join("")}</${list.tag}>`);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    let m: RegExpMatchArray | null;
    if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
      if (!list || list.tag !== "ul") { flush(); list = { tag: "ul", items: [] }; }
      list.items.push(inl(m[1]));
      continue;
    }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      if (!list || list.tag !== "ol") { flush(); list = { tag: "ol", items: [] }; }
      list.items.push(inl(m[1]));
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    flush();
    if ((m = line.match(/^#{1,6}\s+(.*)$/))) out.push(`<p class="ph">${inl(m[1].replace(/\*\*/g, ""))}</p>`);
    else out.push(`<p>${inl(line)}</p>`);
  }
  flush();
  return out.join("");
}

/** Nusxalash uchun toza matn: markdown belgilarisiz + manbalar ro'yxati */
export function plainAnswer(text: string, sources: { n: number; doc_title: string; article_number: string | null; source_url: string }[]) {
  const body = text.replace(/\*\*/g, "").replace(/^#{1,6}\s+/gm, "").replace(/^\s*[*•]\s+/gm, "• ").trim();
  const used = new Set([...text.matchAll(CITE)].flatMap((m) => m[1].split(/\s*[,;]\s*/).map(Number)));
  const list = sources.filter((s) => used.has(s.n))
    .map((s) => `[${s.n}] ${niceTitle(s.doc_title)}${s.article_number ? `, ${s.article_number}-modda` : ""} — ${s.source_url}`);
  return body + (list.length ? `\n\nManbalar:\n${list.join("\n")}` : "") + "\n\nBu yuridik maslahat emas. Rasmiy matn: lex.uz";
}

/** "OʻZBEKISTON RESPUBLIKASI ..." kabi KATTA harfli nomlarni oddiy yozuvga keltiradi */
export function niceTitle(t: string) {
  const L = t.replace(/[^A-Za-z]/g, "");
  if (L.replace(/[^A-Z]/g, "").length / Math.max(L.length, 1) < 0.7) return t;
  const s = t.toLowerCase().replace(/oʻzbekiston respublikasi/g, "Oʻzbekiston Respublikasi").replace(/oʻzbekiston/g, "Oʻzbekiston");
  return s[0].toUpperCase() + s.slice(1);
}
