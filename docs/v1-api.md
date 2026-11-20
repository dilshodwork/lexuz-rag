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
* **Query rewriting** (`lexrag/rewrite.py`): asl savolning eng yaqin moddasi uzoq bo'lsa (cosine < 0.64), LLM
  savolni qonun atamalari bilan qisqa so'rovga aylantiradi ("qarzni sud orqali undirish muddati" → "Da'vo muddati,
  Fuqarolik kodeksi"). Qidiruv asl savol va shu so'rov bilan alohida bajarilib, RRF bilan birlashtiriladi.
  "Bazada yo'q" qarori asl savol bo'yicha qoladi. Natija keshlanadi (bir xil savol — bir xil so'rov).
  `debug.rewritten_query`, `debug.rewrite_applied`, `timing.rewrite_ms`. O'chirish: `QUERY_REWRITE=0`.
  Chegara va og'irlik faqat DEV'da tanlangan; TEST'da (sozlashda qaralmagan 80 savol, faqat qidiruv):
  Hit@5 83.8% → 93.8%, MRR@5 0.689 → 0.774.
* **`no_answer`:** eng yaqin bo'lak cosine < 0.48 bo'lsa, LLM chaqirilmaydi. LLM manbada javob yo'q desa ham
  `no_answer: true` qaytadi. Ikkala holatda `citations: []`. Sababi `debug.no_answer_reason` da yoziladi.
* **`citations`:** faqat javobda `[n]` bilan keltirilgan bo'laklar (`ref` = `contexts[].rank`). `quote` — bo'lak
  matnidan aynan olingan gap. Kontekstda yo'q `[n]` javobdan olib tashlanadi.
* **Takrorlanuvchanlik:** qidiruv deterministik. `temperature` (standart 0) va `seed` LLM'ga uzatiladi.
  LLM provayderi band bo'lsa, zaxira modelga o'tadi. Javobni qaysi model yozgani har savolda `llm_model` da,
  batch bo'yicha `system.llm_model` da (bir nechta bo'lsa vergul bilan, `system.llm_models_used`) ko'rinadi;
  sozlangan model - `system.llm_model_configured`.
* **`as_of_date`** qo'llab-quvvatlanmaydi: indeksda faqat 31.10.2026 holatidagi tahrir bor
  (`debug.as_of_date_note`).
* **Idempotentlik:** bir xil `batch_id` bilan bir xil so'rov saqlangan natijani qaytaradi. Boshqa mazmun bo'lsa
  `409` qaytadi. Saqlangan natijada `retryable: true` xatoli savollar bo'lsa, qayta yuborilganda faqat o'shalar
  qayta hisoblanadi. Natijalar o'chirilmaydi.
* **Vaqt:** qidiruv ~0.4 s; qolgani LLM. Batch ichidagi savollar parallel (`V1_CONCURRENCY`, standart 3).
  Bitta savolda LLM javobini kutish 45 s bilan cheklangan (`V1_LLM_DEADLINE_S`, barcha zaxira modellar bilan);
  oshsa savol `status: timeout`, `LLM_TIMEOUT`, `retryable: true`. Batch 110 s ichida tugamasa `202` qaytadi,
  natijani `GET` bilan olish mumkin.
* **Rate limit:** bitta kalitga soniyasiga 5 ta POST; oshsa `429` + `Retry-After`.

## Tekshirish

`scripts/v1_check.py` spetsifikatsiyaning 7-bo'limidagi checklist'ni tekshiradi:

```bash
.venv/bin/python scripts/v1_check.py                                          # lokal, LLM mock
RAG_TEST_KEY=... .venv/bin/python scripts/v1_check.py --url https://92-5-109-49.sslip.io --live-llm
```

`scripts/spec_run.py` ustoz qiladigan testni takrorlaydi (1- va 6-bo'limlar): 100 savollik CSV → 10 ta batch
ketma-ket, javoblar `eval/spec_runs/<run_id>/bNN.json`, metrikalar `report.md` / `report.json`.

```bash
.venv/bin/python scripts/spec_run.py build      # eval/spec_testset.csv (eval/questions.jsonl dan)
RAG_TEST_KEY=... .venv/bin/python scripts/spec_run.py run --url https://92-5-109-49.sslip.io --run-id eval-1
.venv/bin/python scripts/spec_run.py score --dir eval/spec_runs/eval-1     # LLM'siz qayta hisoblash
```

To'plam: 90 ta javobi bor savol (80 TEST + 10 DEV) va 10 ta javobsiz. Kategoriyalar taqribiy: eval to'plamida
"o'zgargan normalar" va "noaniq savol" belgisi yo'q. `expected_answer` bo'sh, shuning uchun Answer correctness va
Faithfulness hisoblanmaydi (LLM-hakam yoki qo'lda kerak).

### Run `spec-2026-11-19` (Oracle, gemini-3.1-flash-lite, bepul tarif)

| Metrika | Natija | Maqsad | |
|---|---|---|---|
| Hit@5 (hujjat) | 91.1% | ≥ 90% | ✅ |
| Hit@5 (modda) | 84.4% | ≥ 80% | ✅ |
| MRR | 0.699 | ≥ 0.70 | ❌ (0.001) |
| Context precision (hujjat bo'yicha, taqribiy) | 63.6% | ≥ 60% | ✅ |
| Citation accuracy (kutilgan modda keltirilgan, taqribiy) | 93.8% | ≥ 90% | ✅ |
| To'qilgan manba / eskirgan norma | 0 / 0 | 0 / 0 | ✅ |
| No-answer | 10/10 | ≥ 9/10 | ✅ |
| Latency p50 / p95 | 5.3 s / 27.4 s | ≤ 5 / ≤ 12 s | ❌ |
| Xato ulushi | 0% (qayta yuborishdan oldin 3%) | ≤ 2% | ✅ |

* 3 savol birinchi urinishda `LLM_TIMEOUT` (retryable) bo'ldi; spetsifikatsiya bo'yicha o'sha `batch_id` qayta
  yuborilganda faqat o'shalar qayta hisoblandi va javob berdi.
* Javobi bor 9 savolda `no_answer: true` - hammasida kutilgan modda `contexts` da yo'q (qidiruv xatosi), LLM
  to'qimasdan "topilmadi" dedi. Qidiruv xatolari asosan og'zaki "raqamlar" savollarida (Hit@5 72.7%).
* Kechikish: qidiruv ~0.6 s, Gemini bepul tarifida generatsiya p50 4.6 s (oddiy "2+2" so'rovi ham 5–7 s).
  p95 talabini bepul tarifda bajarib bo'lmaydi. Bir run ≈ 352 ming kirish + 25 ming chiqish tokeni.

### Run `spec-2026-11-20-rw` (+ query rewriting, o'sha 100 savol)

| Metrika | 19.11 (rewrite'siz) | 20.11 (rewrite bilan) | Maqsad |
|---|---|---|---|
| Hit@5 (hujjat) | 91.1% | **98.9%** | ≥ 90% ✅ |
| Hit@5 (modda) | 84.4% | **93.3%** | ≥ 80% ✅ |
| MRR | 0.699 | **0.781** | ≥ 0.70 ✅ |
| Context precision (taqribiy) | 63.6% | 72.2% | ≥ 60% ✅ |
| Citation accuracy (taqribiy) | 93.8% | 96.6% | ≥ 90% ✅ |
| To'qilgan manba / eskirgan norma | 0 / 0 | 0 / 0 | 0 ✅ |
| No-answer | 10/10 | 10/10 | ≥ 9/10 ✅ |
| Javobi bor savolga "topilmadi" | 9 | 3 | — |
| Latency p50 / p95 | 5.3 / 27.4 s | 4.5 / 17.5 s | ≤ 5 / ≤ 12 s (p95 ❌) |
| Xato ulushi | 0% | 0% | ≤ 2% ✅ |

* Qayta yozish 49 savolda ishladi; 44 tasi DEV/TEST tajribasidan keshda edi. Yangi savollarda har biriga +1 LLM
  so'rovi (bu run'da 0.5–9 s) qo'shiladi, shuning uchun latency raqami yangi to'plamda biroz yomonroq bo'ladi.
  20.11 ertalab Gemini 19.11 kechqurundagidan tezroq javob berdi - latency farqining bir qismi shundan.
* 13 javobni zaxira model yozdi (3.5-flash 11, 3.8-flash 2) - `system.llm_model` da ko'rinadi (4 xil variant).
* To'plamdagi 10 ta DEV savoli chegarani tanlashda ishlatilgan; qolgan 90 tasi sozlashda qaralmagan.
