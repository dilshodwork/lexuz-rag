// render.ts XSS sinovi: LLM / manba matnidagi HTML ishlamasligi, faqat ruxsat etilgan teglar chiqishi.
//   node scripts/test_render.mjs        (scripts/test_deploy.py ham chaqiradi)
import { renderAnswer, plainAnswer, safeLexUrl } from "../web/src/render.ts";

let fails = 0;
const ok = (c, name, detail = "") => { console.log((c ? "  ok  " : "  XATO") + " " + name + (c ? "" : " - " + detail)); if (!c) fails++; };

const ALLOWED = new Set(["p", "ul", "ol", "li", "strong", "span", "button"]);
const ATTRS = /^(class|data-n|data-c|aria-label|style)$/;
/** HTML'dagi har teg va atributni tekshiradi (DOM'siz, oddiy tokenizator: render.ts faqat shu shakldagi HTML yasaydi) */
function audit(html) {
  const bad = [];
  for (const m of html.matchAll(/<\/?([a-zA-Z0-9-]+)([^>]*)>/g)) {
    const tag = m[1].toLowerCase();
    if (!ALLOWED.has(tag)) bad.push("teg " + tag);
    for (const a of m[2].matchAll(/\s([^\s=]+)(?:="([^"]*)")?/g)) {
      if (!ATTRS.test(a[1])) bad.push("atribut " + a[1]);
      const v = a[2] ?? "";
      if (a[1] === "style" && !/^animation-delay:-\d+ms$/.test(v)) bad.push("style " + v);
      if ((a[1] === "data-n" || a[1] === "data-c") && !/^\d+$/.test(v)) bad.push(a[1] + "=" + v);
    }
  }
  // teglardan tashqaridagi matnda xom < yoki > qolmasin
  const text = html.replace(/<\/?[a-zA-Z0-9-]+(?:\s[^>]*)?>/g, "");
  if (/[<>]/.test(text)) bad.push("xom < yoki >");
  return bad;
}

const PAYLOADS = [
  `<script>alert(1)</script>`,
  `<img src=x onerror=alert(1)>`,
  `**<svg onload=alert(1)>** va [1]`,
  `- <a href="javascript:alert(1)">bos</a>`,
  `1. "><iframe src=//evil>`,
  `### <style>*{display:none}</style>`,
  `Modda [1"><img src=x onerror=alert(1)>] va [2]`,
  `[1, 2] <b onclick=alert(1)>x</b> [99]`,
  `' onmouseover='alert(1)`,
  "\u{E105}<img src=x onerror=alert(1)>\u{E001} gap",
  `&lt;script&gt; allaqachon escape qilingan`,
  `<<<KEYINGI>>> <details open ontoggle=alert(1)>`,
];

for (const [i, p] of PAYLOADS.entries()) {
  for (const live of [false, true]) {
    const html = renderAnswer(p, { maxN: 3, activeN: 1, ...(live ? { times: [], now: 100 } : {}), marks: [{ start: 0, end: 5, i: 2 }] });
    const bad = audit(html);
    ok(!bad.length, `payload ${i + 1}${live ? " (oqim)" : ""}`, bad.join(", ") + " :: " + html.slice(0, 200));
  }
}

const h = renderAnswer("Muddat 21 kun [1][3], qarang [2, 3] va [7].", { maxN: 3 });
ok((h.match(/<button class="cite"/g) || []).length === 4, "[n] tugmalari faqat 1..maxN uchun (4 ta)", h);
ok(!h.includes('data-n="7"') && h.includes("[7]"), "[7] (manba yo'q) oddiy matn bo'lib qoladi");
ok(renderAnswer("a & b < c", { maxN: 0 }) === "<p>a &amp; b &lt; c</p>", "& va < escape");

ok(safeLexUrl("https://lex.uz/uz/docs/-6257288#123") === "https://lex.uz/uz/docs/-6257288#123", "safeLexUrl: lex.uz o'tadi");
for (const u of ["javascript:alert(1)", "https://lex.uz.evil.com/x", "//evil.com", "data:text/html,x", null]) {
  ok(safeLexUrl(u) === "https://lex.uz/", `safeLexUrl rad etadi: ${u}`);
}
ok(plainAnswer("**a** [1]", [{ n: 1, doc_title: "<b>X</b>", article_number: "5", source_url: "https://lex.uz/x" }]).includes("<b>X</b>"),
  "plainAnswer - oddiy matn (HTML sifatida ishlatilmaydi)");

process.exit(fails ? 1 : 0);
