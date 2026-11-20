"""Dalil RAG API - sinov tartibi (PDF). HTML + headless Chrome.

    python docs/sinov-tartibi/build.py      # -> docs/sinov-tartibi/Dalil_RAG_API_sinov_tartibi.pdf
"""
from __future__ import annotations

import html
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_HTML = HERE / "sinov_tartibi.html"
OUT_PDF = HERE / "Dalil_RAG_API_sinov_tartibi.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

URL = "https://92-5-109-49.sslip.io"
DOCS = "https://github.com/dilshodwork/lexuz-rag/blob/main/docs/v1-api.md"
REPO = "https://github.com/dilshodwork/lexuz-rag"


def code(s: str) -> str:
    return f"<pre><code>{html.escape(s.strip(chr(10)))}</code></pre>"


def tests(rows: list[tuple[str, str, str, str, str]]) -> str:
    out = ['<table class="tc"><thead><tr><th>ID</th><th>Tekshiruv</th><th>Soʻrov</th>'
           '<th>Kutilgan natija</th><th>Spek.</th><th>Natija</th></tr></thead><tbody>']
    for tid, name, req, exp, ref in rows:
        out.append(f'<tr><td class="id">{tid}</td><td>{name}</td><td class="req">{req}</td>'
                   f'<td>{exp}</td><td class="ref">{ref}</td><td class="box">☐</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


REQ_EXAMPLE = """
{
  "run_id": "eval-2026-11-25",
  "batch_id": "eval-2026-11-25-b01",
  "batch_index": 1,
  "total_batches": 10,
  "options": {
    "top_k": 5, "return_contexts": true, "return_debug": true,
    "temperature": 0, "seed": 42, "answer_language": "auto"
  },
  "items": [
    {"id": "q001", "question": "Yillik asosiy mehnat taʼtilining eng kam muddati qancha?", "language": "uz-Latn"},
    {"id": "q002", "question": "Какой срок исковой давности установлен Гражданским кодексом?", "language": "ru"},
    {"id": "q003", "question": "Президент қанча муддатга сайланади?"},
    {"id": "q004", "question": "Marsda yer sotib olish tartibi qanday?"}
  ]
}"""

RESP_EXAMPLE = """
{
  "run_id": "spec-2026-11-20-rw", "batch_id": "spec-2026-11-20-rw-b01", "status": "completed",
  "system": {
    "pipeline_version": "1.0.0", "llm_provider": "gemini",
    "llm_model": "gemini-3.1-flash-lite", "llm_model_configured": "gemini-3.1-flash-lite",
    "llm_models_used": ["gemini-3.1-flash-lite"], "embedding_model": "BAAI/bge-m3",
    "reranker": null, "retrieval": "hybrid: bge-m3 dense + BM25, RRF",
    "index_version": "lex-idx-2026-10-31-3f56d80b", "lex_snapshot_date": "2026-10-31"
  },
  "timing": {"received_at": "2026-11-20T10:14:59+05:00",
             "completed_at": "2026-11-20T10:15:17+05:00", "total_ms": 18023},
  "summary": {"total": 10, "ok": 9, "no_answer": 1, "error": 0, "timeout": 0},
  "results": [{
    "id": "q002", "status": "ok", "no_answer": false, "answer_language": "uz-Latn",
    "answer": "Oʻzbekiston Respublikasi Mehnat kodeksining 160-moddasiga koʻra, xodim ... oʻn toʻrt
               kalendar kun oldin ish beruvchini yozma shaklda ogohlantirgan holda bekor qilishga haqli [2]. ...",
    "confidence": 0.657,
    "citations": [{
      "ref": 2, "doc_id": "lex:6257288", "doc_title": "Oʻzbekiston Respublikasining Mehnat kodeksi",
      "doc_type": "kodeks", "url": "https://lex.uz/uz/docs/-6257288",
      "article_url": "https://lex.uz/uz/docs/-6257288#-6261538",
      "article": "160-modda", "part": null, "edition_date": "2026-10-15", "doc_status": "amalda",
      "chunk_id": "6257288_0159_160_1",
      "quote": "Xodim nomuayyan muddatga tuzilgan mehnat shartnomasini ... bekor qilishga haqli."
    }],
    "contexts": [
      {"rank": 1, "chunk_id": "6257288_0164_165_1", "doc_id": "lex:6257288", "article": "165-modda",
       "retrieval_score": 0.6575, "fusion_score": 0.01719, "rerank_score": null,
       "used_in_answer": false, "text": "Ish beruvchi oʻzining mehnat shartnomasini ..."},
      {"rank": 2, "chunk_id": "6257288_0159_160_1", "doc_id": "lex:6257288", "article": "160-modda",
       "retrieval_score": 0.643, "fusion_score": 0.01694, "rerank_score": null,
       "used_in_answer": true, "text": "Xodim nomuayyan muddatga tuzilgan ..."}
    ],
    "debug": {"rewritten_query": "Ozim xohishim bilan ishdan ketmoqchiman, rahbarni necha kun oldin ...",
              "rewrite_applied": false, "retrieved_total": 5, "best_cosine": 0.6575,
              "no_answer_threshold": 0.48, "no_answer_reason": null, "llm_model": "gemini-3.1-flash-lite"},
    "timing": {"retrieval_ms": 2497, "rewrite_ms": null, "rerank_ms": null,
               "generation_ms": 1498, "total_ms": 3996},
    "usage": {"input_tokens": 4492, "output_tokens": 317},
    "llm_model": "gemini-3.1-flash-lite",
    "error": null
  }]
}"""

CSS = """
@page { size: A4; margin: 17mm 16mm 18mm 16mm;
  @bottom-left { content: "Dalil RAG API · Sinov tartibi · v1.1.0"; font: 7.5pt 'Helvetica Neue', Arial; color: #8a7d80; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 7.5pt 'Helvetica Neue', Arial; color: #8a7d80; } }
:root { --accent:#B3233D; --ink:#1C1517; --muted:#6b5f62; --line:#e6dfdc; --wash:#F6F4F2; --soft:#fbeef0; }
* { box-sizing: border-box; }
body { font: 9.6pt/1.5 'Helvetica Neue', Helvetica, Arial, sans-serif; color: var(--ink); margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
h1 { font-size: 23pt; line-height: 1.15; margin: 0 0 4pt; letter-spacing: -0.3pt; }
h2 { font-size: 13.5pt; margin: 18pt 0 6pt; padding-bottom: 3pt; border-bottom: 1.5pt solid var(--accent);
  break-after: avoid; }
h2 .n { color: var(--accent); margin-right: 6pt; }
h3 { font-size: 10.8pt; margin: 12pt 0 4pt; break-after: avoid; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 7pt; padding-left: 15pt; } li { margin: 0 0 2.5pt; break-inside: avoid; }
code { font: 8.3pt Menlo, 'SF Mono', Consolas, monospace; background: var(--wash); padding: 0 2.5pt; border-radius: 2pt; }
pre { background: var(--wash); border: 0.6pt solid var(--line); border-left: 2.5pt solid var(--accent);
  border-radius: 3pt; padding: 6pt 8pt; margin: 4pt 0 8pt; white-space: pre-wrap; word-break: break-word; }
pre code { background: none; padding: 0; font-size: 7.7pt; line-height: 1.42; }
table { width: 100%; border-collapse: collapse; margin: 4pt 0 9pt; font-size: 8.6pt; }
th { text-align: left; background: var(--ink); color: #fff; font-weight: 600; padding: 4pt 5pt; }
td { padding: 3.5pt 5pt; border-bottom: 0.6pt solid var(--line); vertical-align: top; }
tr { break-inside: avoid; }
tbody tr:nth-child(even) td { background: #fcfbfa; }
.tc td.id { font-weight: 700; color: var(--accent); white-space: nowrap; }
.tc td.req { font-family: Menlo, monospace; font-size: 7.4pt; }
.tc td.ref { color: var(--muted); white-space: nowrap; font-size: 7.8pt; }
.tc td.box { text-align: center; font-size: 11pt; color: var(--muted); }
.tc th:nth-child(1){width:7%} .tc th:nth-child(2){width:21%} .tc th:nth-child(3){width:27%}
.tc th:nth-child(4){width:32%} .tc th:nth-child(5){width:6%} .tc th:nth-child(6){width:7%}
.kv td:first-child { width: 31%; color: var(--muted); }
.head { border-top: 5pt solid var(--accent); padding-top: 12pt; margin-bottom: 10pt; }
.brand { font-weight: 800; letter-spacing: 0.4pt; color: var(--accent); font-size: 10pt; text-transform: uppercase; }
.sub { color: var(--muted); font-size: 10.5pt; margin-bottom: 10pt; }
.note { background: var(--soft); border-left: 2.5pt solid var(--accent); padding: 6pt 9pt; border-radius: 3pt;
  margin: 6pt 0 9pt; break-inside: avoid; }
.note b:first-child { color: var(--accent); }
.ok { color: #1f7a45; font-weight: 700; } .no { color: var(--accent); font-weight: 700; }
.toc { columns: 2; column-gap: 18pt; font-size: 9pt; margin: 0 0 6pt; padding-left: 14pt; }
.small { font-size: 8.2pt; color: var(--muted); }
.sign { break-inside: avoid; } .sign td { height: 20pt; border: 0.6pt solid var(--line); } .sign td.l { width: 14%; color: var(--muted); background: var(--wash); }
"""


def build() -> str:
    h: list[str] = []
    a = h.append
    a(f"<!doctype html><html lang='uz'><head><meta charset='utf-8'><title>Dalil RAG API — sinov tartibi</title>"
      f"<style>{CSS}</style></head><body>")

    # ------------------------------------------------------------ sarlavha
    a("<div class='head'><div class='brand'>Dalil · lex.uz RAG</div>"
      "<h1>RAG API: sinov tartibi va qabul mezonlari</h1>"
      "<div class='sub'>“RAG API — test spetsifikatsiyasi (lex.uz)” (03.11.2026) boʻyicha tekshiruvchi uchun "
      "qoʻllanma</div></div>")
    a("<table class='kv'><tbody>"
      f"<tr><td>Tizim</td><td>Dalil — Oʻzbekiston qonunchiligi boʻyicha RAG tizimi (lex.uz maʼlumotlari)</td></tr>"
      f"<tr><td>Base URL</td><td><code>{URL}</code></td></tr>"
      "<tr><td>API kaliti</td><td>Test uchun alohida kalit, shaxsan beriladi (ushbu hujjatda yoʻq)</td></tr>"
      "<tr><td>Pipeline versiyasi</td><td><code>1.1.0</code> (gibrid qidiruv + query rewriting)</td></tr>"
      "<tr><td>Maʼlumotlar holati</td><td>lex.uz, 31.10.2026: 1618 hujjat (1588 qonun, 28 kodeks, "
      "2 Konstitutsiya), 39 961 boʻlak</td></tr>"
      f"<tr><td>Texnik hujjat</td><td><code>{DOCS}</code></td></tr>"
      f"<tr><td>Manba kod</td><td><code>{REPO}</code></td></tr>"
      "<tr><td>Hujjat sanasi</td><td>20.11.2026</td></tr>"
      "<tr><td>Ishlab chiquvchi</td><td>Dilshod Jumanazarov</td></tr>"
      "</tbody></table>")
    a("<ol class='toc'><li>Maqsad va qamrov</li><li>Kirish maʼlumotlari va cheklovlar</li>"
      "<li>Sinov muhitini tayyorlash</li><li>Sinov bosqichlari (T-01 … T-20)</li>"
      "<li>100 savollik baholash run’i</li><li>Metrikalarni hisoblash qoidalari</li>"
      "<li>Maʼlum cheklovlar</li><li>Ichki sinov natijalari</li>"
      "<li>Spetsifikatsiyaning ochiq savollariga javoblar</li><li>Ilovalar: soʻrov va javob namunasi</li></ol>")

    # ------------------------------------------------------------ 1
    a("<h2><span class='n'>1</span>Maqsad va qamrov</h2>")
    a("<p>Hujjat Dalil RAG API’sini spetsifikatsiya talablari boʻyicha qanday tekshirishni bosqichma-bosqich "
      "koʻrsatadi. U ikki qismdan iborat:</p><ul>"
      "<li><b>Funksional sinov (T-01 … T-20)</b> — spetsifikatsiyaning 2–5 va 7-boʻlimlari: endpointlar, "
      "autentifikatsiya, validatsiya, javob formati, xatolar, idempotentlik, rate limit. Har bir test uchun "
      "soʻrov va kutilgan natija berilgan; “Natija” ustuniga belgi qoʻyiladi.</li>"
      "<li><b>Sifatni baholash</b> — 6-boʻlim: 100 savol, 10 ta batch, retrieval va generatsiya "
      "metrikalari.</li></ul>")
    a("<p>Kutilgan javob va kutilgan manba API’ga yuborilmaydi, ular faqat tekshiruvchida saqlanadi "
      "(3-boʻlim talabi).</p>")

    # ------------------------------------------------------------ 2
    a("<h2><span class='n'>2</span>Kirish maʼlumotlari va cheklovlar</h2>")
    a("<table><thead><tr><th>Endpoint</th><th>Vazifasi</th><th>Kalit</th></tr></thead><tbody>"
      "<tr><td><code>POST /v1/rag/batch</code></td><td>1–10 savol: javob, citations, contexts</td><td>Ha</td></tr>"
      "<tr><td><code>GET /v1/rag/batch/{batch_id}</code></td><td>Saqlangan natija (processing → completed / failed)</td><td>Ha</td></tr>"
      "<tr><td><code>POST /v1/rag/query</code></td><td>Bitta savol (debug): <code>{\"question\": \"…\", \"options\": {…}}</code></td><td>Ha</td></tr>"
      "<tr><td><code>GET /v1/meta</code></td><td>Model, embedding, indeks versiyasi, lex.uz snapshot sanasi</td><td>Yoʻq</td></tr>"
      "<tr><td><code>GET /v1/health</code></td><td>Servis holati (tayyor boʻlmasa 503)</td><td>Yoʻq</td></tr>"
      "</tbody></table>")
    a("<table class='kv'><tbody>"
      "<tr><td>Autentifikatsiya</td><td><code>Authorization: Bearer &lt;kalit&gt;</code>; kalitsiz — 401, notoʻgʻri kalit — 403</td></tr>"
      "<tr><td>Kodlash</td><td><code>Content-Type: application/json; charset=utf-8</code>; oʻzbek lotin, oʻzbek kirill, rus tili</td></tr>"
      "<tr><td>Batch hajmi</td><td><code>items</code> 1–10 ta; savol 1–2000 belgi; <code>top_k</code> 1–20 (standart 5)</td></tr>"
      "<tr><td>Sync / async</td><td>Batch 110 s ichida tugasa — 200; tugamasa — 202 va <code>Retry-After: 5</code>, natija GET orqali</td></tr>"
      "<tr><td>Rate limit</td><td>Bitta kalitga 5 POST/s va 20 GET/s; oshsa 429 + <code>Retry-After: 1</code></td></tr>"
      "<tr><td>Bitta savol</td><td>LLM javobini kutish 45 s bilan cheklangan; oshsa <code>status: timeout</code>, <code>LLM_TIMEOUT</code>, <code>retryable: true</code></td></tr>"
      "<tr><td>Natijalarni saqlash</td><td>Batch natijalari oʻchirilmaydi (talab: kamida 30 kun)</td></tr>"
      "</tbody></table>")

    # ------------------------------------------------------------ 3
    a("<h2><span class='n'>3</span>Sinov muhitini tayyorlash</h2>")
    a("<p>Kerak boʻladi: <code>curl</code> (yoki Postman) va funksional sinov uchun Python 3. "
      "Quyidagi misollar shu ikki oʻzgaruvchidan foydalanadi:</p>")
    a(code(f"""
export URL="{URL}"
export KEY="<berilgan test kaliti>"
H_AUTH="Authorization: Bearer $KEY"
H_JSON="Content-Type: application/json; charset=utf-8"
"""))
    a("<div class='note'><b>Eslatma.</b> Server Oracle Cloud’da doimiy ishlaydi. LLM — Gemini (bepul tarif), "
      "shuning uchun javob vaqti kun davomida oʻzgarib turadi. Bir kunda bir nechta toʻliq run "
      "(har biri ~100–150 LLM soʻrovi) oʻtkazish tavsiya etilmaydi.</div>")

    # ------------------------------------------------------------ 4
    a("<h2><span class='n'>4</span>Sinov bosqichlari</h2>")
    a("<h3>A. Servis holati</h3>")
    a(tests([
        ("T-01", "Servis ishlayapti", "GET /v1/health", "200; <code>ok: true</code>, <code>status: \"ready\"</code>, <code>chunks: 39961</code>", "§2"),
        ("T-02", "Tizim versiyalari", "GET /v1/meta", "200; <code>pipeline_version</code>, <code>llm_model</code>, <code>embedding_model</code>, <code>index_version</code>, <code>lex_snapshot_date</code> toʻldirilgan", "§2, §7"),
    ]))
    a(code("""
curl -s "$URL/v1/health"
curl -s "$URL/v1/meta"
"""))
    a("<h3>B. Autentifikatsiya va validatsiya</h3>")
    a(tests([
        ("T-03", "Kalitsiz soʻrov", "POST /v1/rag/batch, Authorization yoʻq", "401, <code>UNAUTHORIZED</code>", "§5"),
        ("T-04", "Notoʻgʻri kalit", "Authorization: Bearer xato", "403, <code>FORBIDDEN</code>", "§5"),
        ("T-05", "Batch hajmi", "items: 11 ta savol", "400, <code>VALIDATION_ERROR</code> (items ≤ 10)", "§2, §7"),
        ("T-06", "Takroriy id", "items[].id: q1, q1", "400, <code>VALIDATION_ERROR</code>, details: q1", "§5"),
        ("T-07", "Boʻsh savol", "question: \"   \"", "400, <code>VALIDATION_ERROR</code> (question boʻsh)", "§5"),
        ("T-08", "Buzuq JSON", "tana: <code>{not json</code>", "400, <code>VALIDATION_ERROR</code>", "§5"),
    ]))
    a(code("""
# T-05: 11 ta savol -> 400
ITEMS=$(python3 -c 'import json;print(json.dumps([{"id":f"q{i:03d}","question":"Savol?"} for i in range(1,12)]))')
curl -s -X POST "$URL/v1/rag/batch" -H "$H_AUTH" -H "$H_JSON" \\
  -d "{\\"run_id\\":\\"t\\",\\"batch_id\\":\\"t-05\\",\\"batch_index\\":1,\\"total_batches\\":1,\\"items\\":$ITEMS}"
"""))
    a("<h3>C. Funksional sinov: bitta batch</h3>")
    a("<p>Ilova A dagi soʻrovni yuboring: oʻzbek lotin, rus, oʻzbek kirill savollar va bitta javobsiz savol "
      "(T-14 uchun beshinchi savol sifatida <code>{\"id\":\"q005\",\"question\":\"Test\",\"language\":\"xx\"}</code> qoʻshing).</p>")
    a(tests([
        ("T-09", "Batch qayta ishlanadi", "POST /v1/rag/batch (Ilova A + q005)", "200; <code>results</code> soni = <code>items</code> soni, har <code>id</code> bir marta; <code>summary</code>, <code>timing</code>, <code>system</code> bor", "§4, §7"),
        ("T-10", "Manba maydonlari", "results[].citations[]", "<code>doc_id</code>, <code>url</code>, <code>article</code>, <code>part</code>, <code>edition_date</code>, <code>doc_status</code>, <code>quote</code>; <code>quote</code> mos <code>contexts[].text</code> ichida aynan bor", "§4, §7"),
        ("T-11", "Manba kontekstda", "citations[].chunk_id, answer [n]", "har <code>chunk_id</code> <code>contexts</code> ichida; javobdagi har <code>[n]</code> = <code>citations[].ref</code> = <code>contexts[].rank</code>", "§4, §7"),
        ("T-12", "Javobsiz savol", "q004 (Mars)", "<code>status: no_answer</code>, <code>no_answer: true</code>, <code>citations: []</code>, toʻqilgan javob yoʻq", "§4, §7"),
        ("T-13", "Tillar va belgilar", "q001, q002, q003", "<code>answer_language</code>: uz-Latn / ru / uz-Cyrl; javobda oʻ, gʻ, ʻ buzilmagan (\\u escape yoʻq)", "§2, §7"),
        ("T-14", "Savol xatosi izolyatsiyasi", "q005, language: \"xx\"", "HTTP 200; q005: <code>status: error</code>, <code>INVALID_LANGUAGE</code>, <code>retryable: false</code>; qolgan savollar ok", "§5, §7"),
    ]))
    a("<h3>D. Idempotentlik va async</h3>")
    a(tests([
        ("T-15", "Qayta yuborish", "T-09 soʻrovini aynan qayta", "200, darhol; natija avvalgisi bilan bir xil (<code>timing.received_at</code> oʻzgarmaydi)", "§2, §7"),
        ("T-16", "batch_id toʻqnashuvi", "shu batch_id, boshqa items", "409, <code>BATCH_ID_CONFLICT</code>", "§5"),
        ("T-17", "Natijani olish", "GET /v1/rag/batch/{id}; GET …/yoq-batch", "200 <code>status: completed</code>; nomaʼlum id — 404", "§1, §5"),
        ("T-18", "Async rejim", "batch 110 s dan oshganda", "202 <code>{\"batch_id\": …, \"status\": \"processing\"}</code> + <code>Retry-After: 5</code>; GET poll → completed", "§5, §7"),
    ]))
    a("<p class='small'>T-15: JSON kalitlari tartibi va boʻshliqlar ahamiyatsiz — soʻrov mazmuni solishtiriladi. "
      "Saqlangan natijada <code>retryable: true</code> xatoli savollar boʻlsa, qayta yuborilganda faqat oʻshalar qayta "
      "hisoblanadi. T-18 ni sunʼiy chaqirib boʻlmaydi: u LLM sekin ishlaganda tabiiy holda yuz beradi (ichki "
      "run’da kuzatilgan).</p>")
    a("<h3>E. Takrorlanuvchanlik va F. Rate limit</h3>")
    a(tests([
        ("T-19", "Bir xil manbalar", "T-09 savollari, yangi batch_id, temperature 0, seed 42", "har savolda <code>contexts[].chunk_id</code> roʻyxati va tartibi avvalgisi bilan bir xil", "§2, §7"),
        ("T-20", "Rate limit", "1 soniyada 6+ POST (yoki 21+ GET)", "429, <code>RATE_LIMITED</code>, <code>Retry-After: 1</code>", "§2, §5"),
    ]))
    a("<p class='small'>T-19: qidiruv deterministik. Javob matni LLM’ga bogʻliq: Gemini band boʻlsa javobni zaxira model "
      "yozadi, bu <code>results[].llm_model</code> va <code>system.llm_models_used</code> da koʻrinadi.</p>")

    # ------------------------------------------------------------ 5
    a("<h2><span class='n'>5</span>100 savollik baholash run’i</h2>")
    a("<ol><li>Test toʻplamini tayyorlang (spetsifikatsiya formati): <code>id, batch, category, question, "
      "expected_answer, expected_doc_id, expected_article, answerable</code>.</li>"
      "<li>Savollarni 10 ta batch’ga boʻling (q001–q100), har batch’ga har kategoriyadan aralash.</li>"
      "<li>Batch’larni <b>ketma-ket</b> yuboring: b01 javobi kelgach b02. Tavsiya etilgan <code>options</code>: "
      "<code>top_k: 5, return_contexts: true, return_debug: true, temperature: 0, seed: 42</code>.</li>"
      "<li>Javoblar boʻyicha harakat:<ul>"
      "<li>200 — natijani <code>&lt;run_id&gt;/bNN.json</code> ga saqlang;</li>"
      "<li>202 — <code>GET /v1/rag/batch/{batch_id}</code> ni 5 s oraliqda poll qiling;</li>"
      "<li>429 — <code>Retry-After</code> dan keyin qayta;</li>"
      "<li>500 / 503 / 504 — 3 martagacha qayta (5 s, 15 s, 45 s);</li>"
      "<li>savolda <code>retryable: true</code> xato — <b>oʻsha batch_id bilan</b> qayta yuboring (faqat xatoli "
      "savollar qayta hisoblanadi).</li></ul></li>"
      "<li>10 ta batch tugagach, javoblarni test toʻplami bilan <code>id</code> boʻyicha solishtirib, 6-boʻlim "
      "qoidalari bilan metrikalarni hisoblang.</li>"
      "<li>Tizim oʻzgarganda xuddi shu 100 savolni qayta yuboring va run’larni <code>system.pipeline_version</code>, "
      "<code>index_version</code>, <code>llm_model</code> boʻyicha taqqoslang.</li></ol>")
    a("<div class='note'><b>Tayyor vosita.</b> Yuqoridagi tartibni toʻliq bajaradigan skript repozitoriyda bor: "
      "<code>scripts/spec_run.py</code> (faqat Python + httpx). U CSV’ni batch’larga boʻlib ketma-ket yuboradi, "
      "202/429/5xx va retryable xatolarni spetsifikatsiyadagidek qayta ishlaydi, javoblarni "
      "<code>bNN.json</code> ga saqlaydi va <code>report.md</code> / <code>report.json</code> chiqaradi.</div>")
    a(code("""
RAG_TEST_KEY="$KEY" python scripts/spec_run.py run --url "$URL" \\
    --csv test_toplami.csv --run-id eval-2026-11-25
python scripts/spec_run.py score --csv test_toplami.csv --dir eval/spec_runs/eval-2026-11-25
"""))

    # ------------------------------------------------------------ 6
    a("<h2><span class='n'>6</span>Metrikalarni hisoblash qoidalari</h2>")
    a("<h3>Identifikatorlarni moslashtirish</h3><ul>"
      "<li><b>doc_id</b> = <code>lex:</code> + lex.uz URL’idagi hujjat raqami (minus belgisisiz): "
      "<code>https://lex.uz/uz/docs/-6257288</code> → <code>lex:6257288</code>. Indeks qayta qurilganda oʻzgarmaydi.</li>"
      "<li><b>article</b> = <code>&lt;raqam&gt;-modda</code>, lex.uz’dagi yozuv saqlanadi, darajali raqamlar ham: "
      "<code>746¹-modda</code>, <code>497⁴-modda</code>. Kutilgan modda <code>746-1</code> shaklida yozilgan boʻlsa, "
      "solishtirishdan oldin normallashtiring.</li>"
      "<li><b>Modda darajasidagi moslik</b> = <code>doc_id</code> va <code>article</code> ikkalasi mos "
      "(bir xil raqamli modda boshqa kodeksda ham boʻladi).</li>"
      "<li><b>chunk_id</b> — tizimning ichki identifikatori (<code>&lt;hujjat&gt;_&lt;tartib&gt;_&lt;modda&gt;_&lt;boʻlak&gt;</code>); "
      "faqat citations ↔ contexts bogʻlanishi uchun.</li></ul>")
    a("<table><thead><tr><th>Metrika</th><th>Qaysi maydondan</th><th>Hisoblash</th><th>Maqsad</th></tr></thead><tbody>"
      "<tr><td>Hit@5 (hujjat)</td><td><code>contexts[].doc_id</code></td><td><code>rank ≤ 5</code> ichida kutilgan hujjat bormi</td><td>≥ 90%</td></tr>"
      "<tr><td>Hit@5 (modda)</td><td><code>contexts[].doc_id + article</code></td><td><code>rank ≤ 5</code> ichida kutilgan modda bormi</td><td>≥ 80%</td></tr>"
      "<tr><td>MRR</td><td><code>contexts[].rank</code></td><td>1 / (kutilgan moddaning birinchi oʻrni); javobi bor savollar boʻyicha oʻrtacha</td><td>≥ 0.70</td></tr>"
      "<tr><td>Context precision</td><td><code>contexts[]</code> (top-5)</td><td>top-5 dan savolga tegishlilari ulushi</td><td>≥ 60%</td></tr>"
      "<tr><td>Answer correctness</td><td><code>answer</code></td><td>0/1/2 ball (qoʻlda yoki LLM-hakam)</td><td>≥ 1.6</td></tr>"
      "<tr><td>Faithfulness</td><td><code>answer</code>, <code>contexts[].text</code></td><td>javobdagi har daʼvo kontekstda bormi</td><td>≥ 95%</td></tr>"
      "<tr><td>Citation accuracy</td><td><code>citations[]</code></td><td>keltirilgan modda daʼvoni tasdiqlaydimi</td><td>≥ 90%</td></tr>"
      "<tr><td>Toʻqilgan manba</td><td><code>citations[].chunk_id, url</code></td><td>contexts’da yoki lex.uz’da yoʻq havola</td><td>0</td></tr>"
      "<tr><td>Eskirgan norma</td><td><code>citations[].doc_status</code></td><td><code>\"amalda\"</code> dan boshqa holat (<code>kuchini yoʻqotgan</code>, <code>amalda emas</code>)</td><td>0</td></tr>"
      "<tr><td>No-answer aniqligi</td><td><code>no_answer</code></td><td>10 ta javobsiz savoldan nechtasida <code>true</code></td><td>≥ 9/10</td></tr>"
      "<tr><td>Latency</td><td><code>results[].timing.total_ms</code></td><td>savol boʻyicha p50 / p95 (qidiruv + qayta yozish + generatsiya)</td><td>≤ 5 / 12 s</td></tr>"
      "<tr><td>Xato ulushi</td><td><code>results[].status</code></td><td><code>error</code> yoki <code>timeout</code> ulushi</td><td>≤ 2%</td></tr>"
      "</tbody></table>")
    a("<ul><li>Koʻp qismli savolda har qism alohida qidiriladi, shuning uchun <code>contexts</code> <code>top_k</code> "
      "dan koʻp (10 tagacha) boʻlishi mumkin; Hit@5 uchun <code>rank ≤ 5</code> olinadi.</li>"
      "<li><code>confidence</code> — asl savol va eng yaqin modda orasidagi cosine oʻxshashlik (0–1), kalibrlangan "
      "ehtimol emas.</li>"
      "<li>Xato tahlilida <code>debug</code> yordam beradi: <code>no_answer_reason</code> (<code>low_similarity</code> "
      "/ <code>llm_not_found</code>), <code>best_cosine</code>, <code>rewritten_query</code>, <code>rewrite_applied</code>.</li></ul>")

    # ------------------------------------------------------------ 7
    a("<h2><span class='n'>7</span>Maʼlum cheklovlar</h2>")
    a("<table><thead><tr><th>Cheklov</th><th>Izoh</th></tr></thead><tbody>"
      "<tr><td><code>as_of_date</code></td><td>Qoʻllab-quvvatlanmaydi: indeksda faqat 31.10.2026 holatidagi amaldagi tahrir bor. "
      "Parametr qabul qilinadi, izoh <code>debug.as_of_date_note</code> da qaytadi.</td></tr>"
      "<tr><td>Reranker</td><td>Yoʻq, <code>rerank_score: null</code>. jina-reranker-v2 sinovida oʻzbekcha natija yomonlashdi "
      "(Hit@5 84.0% → 80.2%) va savolga +2.5 s qoʻshildi, shuning uchun qoʻshilmadi.</td></tr>"
      "<tr><td><code>part</code> (modda qismi)</td><td>Iqtibos olingan xatboshidan aniqlanadi; bir necha boʻlakka "
      "boʻlingan uzun moddada <code>null</code>.</td></tr>"
      "<tr><td>Latency p95</td><td>Gemini bepul tarifida birinchi token ba’zan 10–40 s kechikadi; p95 ≤ 12 s "
      "kafolatlanmaydi. Qidiruvning oʻzi ~0.4–0.6 s.</td></tr>"
      "<tr><td>Zaxira model</td><td>Asosiy model band boʻlsa, javobni zaxira model yozadi; har javobda <code>llm_model</code> "
      "koʻrsatiladi.</td></tr>"
      "<tr><td>Maʼlumot yangiligi</td><td>Baza avtomatik yangilanmaydi; yangilanganda <code>index_version</code> oʻzgaradi.</td></tr>"
      "</tbody></table>")

    # ------------------------------------------------------------ 8
    a("<h2><span class='n'>8</span>Ichki sinov natijalari</h2>")
    a("<p>Ishlab chiquvchi ushbu tartibni oʻzining 100 savollik toʻplamida (80 TEST + 10 DEV javobi bor savol, "
      "10 javobsiz) jonli serverda bajardi. Bu natijalar mustaqil baholash oʻrnini bosmaydi: tekshiruvchining "
      "savollari boshqacha boʻladi.</p>")
    a("<table><thead><tr><th>Metrika</th><th>19.11 (v1.0.0)</th><th>20.11 (v1.1.0)</th><th>Maqsad</th><th>Holat</th></tr></thead><tbody>"
      "<tr><td>Hit@5 (hujjat)</td><td>91.1%</td><td>98.9%</td><td>≥ 90%</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>Hit@5 (modda)</td><td>84.4%</td><td>93.3%</td><td>≥ 80%</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>MRR</td><td>0.699</td><td>0.781</td><td>≥ 0.70</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>Context precision*</td><td>63.6%</td><td>72.2%</td><td>≥ 60%</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>Citation accuracy*</td><td>93.8%</td><td>96.6%</td><td>≥ 90%</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>Toʻqilgan manba / eskirgan norma</td><td>0 / 0</td><td>0 / 0</td><td>0</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>No-answer aniqligi</td><td>10/10</td><td>10/10</td><td>≥ 9/10</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>Xato ulushi**</td><td>0%</td><td>0%</td><td>≤ 2%</td><td class='ok'>bajarildi</td></tr>"
      "<tr><td>Latency p50 / p95</td><td>5.3 / 27.4 s</td><td>4.5 / 17.5 s</td><td>≤ 5 / 12 s</td><td class='no'>p95 bajarilmadi</td></tr>"
      "<tr><td>Answer correctness, Faithfulness</td><td colspan='2'>hisoblanmagan (kutilgan javob matni yoʻq)</td><td>≥ 1.6 / ≥ 95%</td><td>—</td></tr>"
      "</tbody></table>")
    a("<p class='small'>* Taqribiy: kutilgan hujjat / modda boʻyicha avtomatik, LLM-hakamsiz. ** Birinchi urinishda "
      "19.11 da 3 savol <code>LLM_TIMEOUT</code> (retryable) boʻldi; oʻsha batch_id bilan qayta yuborilganda javob berdi. "
      "20.11 run’ida qayta yozilgan soʻrovlarning bir qismi keshdan olingan, shuning uchun yangi savollarda latency biroz "
      "yuqoriroq boʻlishi kutiladi. Toʻliq javoblar: <code>eval/spec_runs/</code>.</p>")

    # ------------------------------------------------------------ 9
    a("<h2><span class='n'>9</span>Spetsifikatsiyaning ochiq savollariga javoblar</h2>")
    a("<ul><li><b>Maʼlumot qachon olingan, qanchalik tez yangilanadi?</b> lex.uz Milliy bazasi, 31.10.2026 holati "
      "(<code>lex_snapshot_date</code>). Avtomatik yangilanmaydi; yangilanish qoʻlda, <code>index_version</code> bilan belgilanadi.</li>"
      "<li><b>Chunking modda boʻyichami?</b> Ha: 1 modda = 1 boʻlak. Uzun moddalar overlap bilan bir necha boʻlakka "
      "boʻlinadi (maks. 800 token). Shuning uchun <code>article</code> aniq.</li>"
      "<li><b>Kuchini yoʻqotgan hujjatlar indeksdami?</b> Ha, <code>doc_status</code> bilan belgilangan "
      "(<code>kuchini yoʻqotgan</code>, <code>amalda emas</code>). Qidiruv faqat amaldagi hujjatlar boʻyicha va "
      "oʻzgartirish kirituvchi qonunlarsiz ishlaydi.</li>"
      "<li><b>Qidiruv qanday?</b> Gibrid: bge-m3 (dense) + BM25, RRF bilan birlashtiriladi. Eng yaqin modda uzoq "
      "boʻlsa (cosine &lt; 0.64), LLM savolni huquqiy atamalar bilan qayta yozadi va ikkala qidiruv birlashtiriladi; "
      "“bazada yoʻq” qarori asl savol boʻyicha qabul qilinadi (cosine &lt; 0.48 — LLM chaqirilmaydi).</li></ul>")

    # ------------------------------------------------------------ 10
    a("<h2><span class='n'>10</span>Ilovalar</h2>")
    a("<h3>Ilova A. Soʻrov namunasi (POST /v1/rag/batch)</h3>")
    a(code(REQ_EXAMPLE))
    a(code("""
curl -s -X POST "$URL/v1/rag/batch" -H "$H_AUTH" -H "$H_JSON" --data-binary @ilova_a.json
"""))
    a("<h3>Ilova B. Javob namunasi (qisqartirilgan, haqiqiy run’dan)</h3>")
    a("<p class='small'>Run <code>spec-2026-11-20-rw</code>, savol q002. Matnlar “…” bilan qisqartirilgan, qiymatlar "
      "oʻzgartirilmagan. Bu run vaqtida versiya raqami hali 1.0.0 edi (kod 1.1.0, raqam keyin koʻtarilgan).</p>")
    a(code(RESP_EXAMPLE))
    a("<h3>Ilova C. Xato kodlari</h3>")
    a("<table><thead><tr><th>Daraja</th><th>Kod</th><th>Qachon</th><th>retryable</th></tr></thead><tbody>"
      "<tr><td>HTTP 400</td><td><code>VALIDATION_ERROR</code></td><td>11+ savol, takroriy id, boʻsh savol, buzuq JSON</td><td>—</td></tr>"
      "<tr><td>HTTP 401 / 403</td><td><code>UNAUTHORIZED</code> / <code>FORBIDDEN</code></td><td>kalit yoʻq / notoʻgʻri</td><td>—</td></tr>"
      "<tr><td>HTTP 404</td><td><code>NOT_FOUND</code></td><td>nomaʼlum batch_id</td><td>—</td></tr>"
      "<tr><td>HTTP 409</td><td><code>BATCH_ID_CONFLICT</code></td><td>shu batch_id boshqa mazmun bilan</td><td>—</td></tr>"
      "<tr><td>HTTP 429</td><td><code>RATE_LIMITED</code></td><td>rate limit oshdi</td><td>Retry-After</td></tr>"
      "<tr><td>HTTP 503</td><td><code>INDEX_UNAVAILABLE</code></td><td>server ishga tushmoqda</td><td>Retry-After</td></tr>"
      "<tr><td>Savol</td><td><code>LLM_TIMEOUT</code></td><td>LLM 45 s ichida javob bermadi (<code>status: timeout</code>)</td><td>true</td></tr>"
      "<tr><td>Savol</td><td><code>LLM_ERROR</code></td><td>LLM band, kvota yoki ulanish xatosi</td><td>true*</td></tr>"
      "<tr><td>Savol</td><td><code>RETRIEVAL_FAILED</code></td><td>qidiruv xatosi</td><td>true</td></tr>"
      "<tr><td>Savol</td><td><code>INVALID_LANGUAGE</code></td><td><code>language</code> uz-Latn / uz-Cyrl / ru emas</td><td>false</td></tr>"
      "</tbody></table>")
    a("<p class='small'>* Serverda LLM sozlanmagan boʻlsa <code>retryable: false</code>.</p>")

    a("<h3>Tasdiqlash</h3>")
    a("<table class='sign'><tbody><tr><td class='l'>Tekshiruvchi</td><td></td><td class='l'>Sana</td><td></td></tr>"
      "<tr><td class='l'>Run ID</td><td></td><td class='l'>Xulosa</td><td></td></tr></tbody></table>")
    a("</body></html>")
    return "".join(h)


def main():
    OUT_HTML.write_text(build(), encoding="utf-8")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(OUT_PDF)


if __name__ == "__main__":
    main()
