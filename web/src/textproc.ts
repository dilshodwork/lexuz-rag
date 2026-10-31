/* LLM javobini qayta ishlash (o'z kaliti yo'li: oqim brauzerda o'qiladi). Serverdagi nusxasi bilan bir xil:
   * lexrag/lang.py: FollowupSplitter, parse_followups, NOT_FOUND_RE
   * lexrag/translit.py: lat_to_cyr, LatToCyrStream
   * lexrag/rag.py: AnswerStream
   Qaysi qoida qo'llanishini server aytadi (/api/context -> post). scripts/test_stage2.py ikkala nusxani bir xil
   misollarda solishtiradi. Bu fayl hech narsa import qilmaydi (node bilan to'g'ridan-to'g'ri ishga tushadi). */

// ---------------------------------------------------------------- "topilmadi" iborasi
export const NOT_FOUND = /^\W*(Bazadagi hujjatlarda bu savolga[^.]*topilmadi|В базе не найден)/i;
/** Ko'rinadigan matn boshidagi "topilmadi" gapi (lotin, kirill yoki ruscha) - izoh qismi qoladi */
export const NOT_FOUND_LEAD = /^\W*(Bazadagi hujjatlarda[^.]*topilmadi|Базадаги ҳужжатларда[^.]*топилмади|В базе не найден[^.]*)\.?\s*/i;

// ---------------------------------------------------------------- keyingi savollar
const MARKER_RE = /\**\s*<{2,3}\s*(?:KEYINGI|КЕЙИНГИ)\s*>{2,3}\s*\**/i;
const HOLD = 24;
const rstripChars = (s: string, chars: string) => { let e = s.length; while (e > 0 && chars.includes(s[e - 1])) e--; return s.slice(0, e); };
const stripChars = (s: string, chars: string) => {
  let a = 0, e = s.length;
  while (a < e && chars.includes(s[a])) a++;
  while (e > a && chars.includes(s[e - 1])) e--;
  return s.slice(a, e);
};

export class FollowupSplitter {
  buf = "";
  tail: string | null = null;

  feed(piece: string): string {
    if (this.tail !== null) { this.tail += piece; return ""; }
    this.buf += piece;
    const m = MARKER_RE.exec(this.buf);
    if (m) {
      const out = this.buf.slice(0, m.index);
      this.tail = this.buf.slice(m.index + m[0].length);
      this.buf = "";
      return rstripChars(out, " *\n");
    }
    let lt = this.buf.indexOf("<", Math.max(0, this.buf.length - HOLD));
    if (lt < 0) lt = this.buf.length;
    // oxiridagi bo'sh joy va "**" ham ushlab turiladi: ajratgich "**<<<KEYINGI>>>**" bo'lib kelishi mumkin
    const tail = rstripChars(this.buf.slice(0, lt), " \n*").length;
    const out = this.buf.slice(0, tail);
    this.buf = this.buf.slice(tail);
    return out;
  }

  flush(): string { const out = this.buf; this.buf = ""; return out; }

  followups(): string[] { return parseFollowups(this.tail || ""); }
}

export function parseFollowups(tail: string): string[] {
  const t = tail.trim();
  let items: string[] = [];
  if (t.startsWith("[")) {
    try { items = (JSON.parse(t.slice(0, t.lastIndexOf("]") + 1)) as unknown[]).map(String); } catch { items = []; }
  }
  if (!items.length) items = t.split(/\r?\n/);
  const out: string[] = [];
  for (let x of items) {
    x = x.replace(/^\s*(?:[-*•–]|\d+[.)])\s*/, "").trim();
    x = stripChars(x, "\"«»“”*").trim();
    x = x.replace(/\[\d+\]/g, "").trim();
    if (x && !"?.!".includes(x[x.length - 1])) x += "?";
    if (x.length >= 6 && x.length <= 160 && !out.includes(x)) out.push(x);
  }
  return out.slice(0, 3);
}

// ---------------------------------------------------------------- lotin -> kirill
const L2C: Record<string, string> = {
  a: "а", b: "б", d: "д", e: "е", f: "ф", g: "г", h: "ҳ", i: "и", j: "ж", k: "к", l: "л", m: "м", n: "н", o: "о",
  p: "п", q: "қ", r: "р", s: "с", t: "т", u: "у", v: "в", x: "х", y: "й", z: "з", c: "к", w: "в",
};
const OKINA = "ʻ'‘’`´";
const TUTUQ = "ʼ";
const VOW = "aeiouAEIOU";
const KEEP = /https?:\/\/\S+|www\.\S+|lex\.uz\S*|\[\d+(?:\s*[,;]\s*\d+)*\]|\b[IVXL]{1,6}\b(?=[\s.,;:)\-]|$)/g;
const TS = /^ts(?=iya|ion|ent|ikl|irk)/i;
const isAlpha = (c: string) => !!c && /\p{L}/u.test(c);
const isUpper = (c: string) => !!c && c !== c.toLowerCase() && c === c.toUpperCase();

function l2cWord(s: string): string {
  const out: string[] = [];
  let i = 0;
  const n = s.length;
  while (i < n) {
    const ch = s[i], low = ch.toLowerCase();
    const nxt = i + 1 < n ? s[i + 1] : "", prev = i > 0 ? s[i - 1] : "";
    const up = isUpper(ch);
    const wordUp = up && (isUpper(nxt) || isUpper(prev));
    let cyr: string | undefined, step = 1;
    if ((low === "o" || low === "g") && nxt && OKINA.includes(nxt)) { cyr = low === "o" ? "ў" : "ғ"; step = 2; }
    else if (low === "s" && nxt.toLowerCase() === "h") { cyr = "ш"; step = 2; }
    else if (low === "c" && nxt.toLowerCase() === "h") { cyr = "ч"; step = 2; }
    else if (low === "y" && nxt && "ouae".includes(nxt.toLowerCase()) && !(nxt.toLowerCase() === "o" && i + 2 < n && OKINA.includes(s[i + 2]))) {
      const v = nxt.toLowerCase();
      cyr = v === "e" ? (!isAlpha(prev) || VOW.includes(prev) ? "е" : "ъе") : ({ o: "ё", u: "ю", a: "я" } as Record<string, string>)[v];
      step = 2;
    } else if (low === "t" && TS.test(s.slice(i))) { cyr = "ц"; step = 2; }
    else if (low === "e") cyr = !isAlpha(prev) || VOW.includes(prev) ? "э" : "е";
    else if (ch === TUTUQ || (OKINA.includes(ch) && isAlpha(prev) && isAlpha(nxt))) cyr = "ъ";
    else cyr = L2C[low];
    if (cyr === undefined) { out.push(ch); i++; continue; }
    if (up) cyr = wordUp ? cyr.toUpperCase() : cyr[0].toUpperCase() + cyr.slice(1);
    out.push(cyr);
    i += step;
  }
  return out.join("");
}

export function latToCyr(text: string): string {
  const out: string[] = [];
  let last = 0;
  for (const m of text.matchAll(KEEP)) {
    out.push(l2cWord(text.slice(last, m.index)));
    out.push(m[0]);
    last = m.index! + m[0].length;
  }
  out.push(l2cWord(text.slice(last)));
  return out.join("");
}

export class LatToCyrStream {
  buf = "";
  feed(piece: string): string {
    this.buf += piece;
    const cut = Math.max(this.buf.lastIndexOf(" "), this.buf.lastIndexOf("\n"));
    if (cut < 0) return "";
    const done = this.buf.slice(0, cut + 1);
    this.buf = this.buf.slice(cut + 1);
    return latToCyr(done);
  }
  flush(): string { const d = this.buf; this.buf = ""; return latToCyr(d); }
}

// ---------------------------------------------------------------- javob oqimi (rag.AnswerStream)
export type PostRules = { marker: string; translit: "lat2cyr" | null };

export class AnswerStream {
  split = new FollowupSplitter();
  cyr: LatToCyrStream | null;
  raw = "";
  constructor(post: PostRules | null | undefined) { this.cyr = post?.translit === "lat2cyr" ? new LatToCyrStream() : null; }
  feed(piece: string): string {
    this.raw += piece;
    const out = this.split.feed(piece);
    return this.cyr ? this.cyr.feed(out) : out;
  }
  flush(): string {
    const out = this.split.flush();
    return this.cyr ? this.cyr.feed(out) + this.cyr.flush() : out;
  }
  followups(): string[] {
    const f = this.split.followups();
    return this.cyr ? f.map(latToCyr) : f;
  }
  notFound(): boolean { return NOT_FOUND.test(this.raw); }
}
