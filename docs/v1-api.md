# Dalil — test API (/v1)

"RAG API — test spetsifikatsiyasi (lex.uz)" (03.11.2026) bo'yicha.

* **Base URL:** `https://92-5-109-49.sslip.io`
* **Autentifikatsiya:** `Authorization: Bearer <API_KEY>` (kalit alohida beriladi)
* **Kodlash:** `application/json; charset=utf-8`, o'zbek lotin / kirill va rus tili

| Endpoint | Vazifasi |
|---|---|
| `POST /v1/rag/batch` | 1–10 savol → javob, `citations`, `contexts` |
| `GET /v1/rag/batch/{batch_id}` | Saqlangan natija: `processing` → `completed` / `failed` |
| `POST /v1/rag/query` | Bitta savol (debug): `{"question": "...", "options": {...}}` |
| `GET /v1/meta` | LLM, embedding, indeks versiyasi, lex.uz snapshot sanasi |
| `GET /v1/health` | Servis holati (kalitsiz) |

Request va response formati spetsifikatsiyaning 3–5-bo'limlaridagidek. Misol:

```bash
curl -s https://92-5-109-49.sslip.io/v1/rag/batch \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"run_id":"eval-1","batch_id":"eval-1-b01","batch_index":1,"total_batches":10,
       "options":{"top_k":5,"return_contexts":true,"return_debug":true,"temperature":0,"seed":42},
       "items":[{"id":"q001","question":"Yillik asosiy mehnat taʼtilining eng kam muddati qancha?"}]}'
```

## Tizim haqida (spetsifikatsiyaning ochiq savollari)

* **Ma'lumot:** lex.uz Milliy bazasi, 31.10.2026 holati: 1588 qonun, 28 kodeks, 2 Konstitutsiya
  (1618 hujjat, 39 961 bo'lak). Avtomatik yangilanmaydi; yangilanganda `index_version` o'zgaradi.
* **Chunking:** modda bo'yicha (1 modda = 1 bo'lak). Uzun moddalar overlap bilan bir necha bo'lakka bo'linadi
  (maks. 800 token). Shuning uchun `article` aniq. `part` (modda qismi, xatboshi) iqtibos olingan xatboshidan
  aniqlanadi; bo'lingan uzun moddada `null`.
* **Kuchini yo'qotgan hujjatlar** indeksda bor va `doc_status` bilan belgilangan. Qidiruv faqat amaldagi
  hujjatlar va o'zgartirish kirituvchi qonunlarsiz ishlaydi.
* **`doc_id`:** `lex:<lex.uz hujjat raqami>`. Bu `url` dagi raqam, minus belgisisiz:
  `https://lex.uz/uz/docs/-6257288` → `lex:6257288`. Indeks qayta qurilganda o'zgarmaydi.
* **Qidiruv:** gibrid. bge-m3 (dense) va BM25 natijalari RRF bilan birlashtiriladi; reranker yo'q (`rerank_score: null`).
  `contexts[].retrieval_score` — savol va bo'lak orasidagi cosine o'xshashlik (0–1), `fusion_score` — RRF bali.
  Bir necha qismli savolda har qism alohida qidiriladi, shunda `contexts` `top_k` dan ko'p (10 tagacha) bo'lishi mumkin.
* **`no_answer`:** eng yaqin bo'lak cosine < 0.48 bo'lsa, LLM chaqirilmaydi. LLM manbada javob yo'q desa ham
  `no_answer: true` qaytadi. Ikkala holatda `citations: []`. Sababi `debug.no_answer_reason` da yoziladi.
* **`citations`:** faqat javobda `[n]` bilan keltirilgan bo'laklar (`ref` = `contexts[].rank`). `quote` — bo'lak
  matnidan aynan olingan gap. Kontekstda yo'q `[n]` javobdan olib tashlanadi.
* **Takrorlanuvchanlik:** qidiruv deterministik. `temperature` (standart 0) va `seed` LLM'ga uzatiladi.
  LLM provayderi band bo'lsa, zaxira modelga o'tadi. Qaysi model javob berganini `debug.llm_model` ko'rsatadi.
* **`as_of_date`** qo'llab-quvvatlanmaydi: indeksda faqat 31.10.2026 holatidagi tahrir bor
  (`debug.as_of_date_note`).
* **Idempotentlik:** bir xil `batch_id` bilan bir xil so'rov saqlangan natijani qaytaradi. Boshqa mazmun bo'lsa
  `409` qaytadi. Saqlangan natijada `retryable: true` xatoli savollar bo'lsa, qayta yuborilganda faqat o'shalar
  qayta hisoblanadi. Natijalar o'chirilmaydi.
* **Vaqt:** savol ~1.5–3 s. Batch 110 s ichida tugamasa `202` qaytadi, natijani `GET` bilan olish mumkin.
* **Rate limit:** bitta kalitga soniyasiga 5 ta POST; oshsa `429` + `Retry-After`.

## Tekshirish

`scripts/v1_check.py` spetsifikatsiyaning 7-bo'limidagi checklist'ni tekshiradi:

```bash
.venv/bin/python scripts/v1_check.py                                          # lokal, LLM mock
RAG_TEST_KEY=... .venv/bin/python scripts/v1_check.py --url https://92-5-109-49.sslip.io --live-llm
```
