# lex.uz "Qonunlar" -> RAG baza

lex.uz Milliy bazasidagi "Qonunlar" bo'limidagi barcha hujjatlarni (1588 ta) va kodekslarni (28 ta,
amaldagi va kuchini yo'qotgan tahrirlar) yig'ib, tozalab, moddalar bo'yicha chunklarga bo'ladi va
ChromaDB vektor bazasiga yozadi. To'plamlar `lexrag/config.py` dagi `COLLECTIONS` da.

## Sayt haqida (1-bosqich natijasi)

| Nima | Topilgani |
|---|---|
| Qonunlar ro'yxati | `https://lex.uz/uz/search/nat?lang=4&sort_id=3975&form_id=3968` (bosh sahifadagi "Qonunlar 1 588" havolasi). `lang=4` - o'zbek lotin, `form_id=3968` - "Qonun" shakli (kodekslar alohida: `form_id=3964`). |
| Sahifalash | ASP.NET WebForms postback: sahifada 20 ta, 80 sahifa. URL o'zgarmaydi; keyingi sahifa `__VIEWSTATE` + `__EVENTTARGET=ucFoundActsControl$LinkButton1` bilan POST. |
| Hujjat URL | `https://lex.uz/uz/docs/<id>`. Manfiy id (`-6257288`) - kirillcha asl hujjatning lotin versiyasi. Ro'yxatdagi 1587 ta id manfiy. |
| Matn | Server tomonda HTML bo'lib keladi, `#divCont` ichida. JS/API kerak emas, shuning uchun Playwright emas, httpx + BeautifulSoup. |
| Amaldagi tahrir | Sahifa standart holatda eng oxirgi tahrirni ko'rsatadi; eski tahrirlar `?ONDATE=dd.mm.yyyy`. Oxirgi tahrir sanasi `.lx_date_selected` dan olinadi. |
| Metadata | Sahifa sarlavhasi (rekvizit, kuchga kirish sanasi) + "Asosiy rekvizitlar" kartochkasi `https://lex.uz/uz/actinfo/card1/<id>` (organ, sana, raqam, holat). |
| O'zgartirish izohlari | Alohida `CHANGES_ORIGINS` elementlarida; "Oldingi tahrirga qarang" va "LexUZ sharhi" - `COMMENT`. |
| robots.txt | Yo'q (`/robots.txt` 404 sahifaga yo'naltiradi). Shunga qaramay so'rovlar orasida 1-2 s pauza. |
| API | Network'da ro'yxat/matn uchun JSON so'rov yo'q (faqat reklama skriptlari). |

## O'rnatish

Python 3.11+ (3.13 da sinalgan). PyTorch kerak emas: embedding ONNX Runtime (fastembed) orqali,
shuning uchun Intel Mac'da ham ishlaydi.

```bash
cd lexuz-rag
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ishga tushirish

```bash
# 1. Ro'yxat (80 sahifa, ~3 daqiqa). To'xtasa, oxirgi saqlangan sahifadan davom etadi.
python -m lexrag list

# 2. Sinov: ro'yxat bo'ylab teng taqsimlangan 10 ta qonun
python -m lexrag fetch --limit 10
python -m lexrag parse --limit 10
python -m lexrag chunk
python -m lexrag verify --n 4      # saytdagi jonli matn bilan solishtirish
python -m lexrag report            # -> report.md

# 3. Hammasi (~1.5 soat yuklash + bir necha soat embedding). Bitta buyruq bilan:
bash scripts/run_full.sh           # log: data/state/full_run.log; to'xtasa qayta ishga tushiring
# yoki bosqichma-bosqich:
python -m lexrag fetch             # to'xtab qolsa qayta ishga tushiring - raw/ dagilar qayta yuklanmaydi
python -m lexrag parse
python -m lexrag chunk             # --merge-short: bir bob ichidagi qisqa moddalarni ~300 tokengacha birlashtirish
python -m lexrag verify --n 4
python -m lexrag report
# yoki bittada:  python -m lexrag all

# 4. Vektor baza va qidiruv
python -m lexrag index                                  # BAAI/bge-m3 (standart)
python -m lexrag index --model intfloat/multilingual-e5-large
python -m lexrag search "Mikromoliya tashkiloti bankka aylanishi mumkinmi?" -k 5   # gibrid: bge-m3 + BM25 (RRF)
python -m lexrag eval                                   # qidiruv sifati: eval/questions.jsonl -> eval/results.md
python -m lexrag search "..." --mode dense              # faqat ma'no bo'yicha (taqqoslash uchun)

# 5. RAG javob (LLM). Avval: cp .env.example .env  va .env ga API kalitni o'zingiz yozing
python -m lexrag ask "Yillik mehnat taʼtilining eng kam muddati necha kun?"
python -m lexrag ask "Президент қанча муддатга сайланади?"   # kirillcha savol ham ishlaydi
python -m lexrag search "..." --all-status              # kuchini yo'qotgan hujjatlar ham
python -m lexrag search "..." --include-amending        # o'zgartirish kirituvchi qonunlar ham
```

Qidiruv standart holatda faqat amaldagi hujjatlarni qidiradi (aks holda 1995-yilgi eski Mehnat kodeksi
yangisidan yuqori chiqishi mumkin) va o'zgartirish kirituvchi qonunlarni (743 ta, `is_amending_law=true`) chiqarib
tashlaydi: ularning matni "... so'zlar bilan almashtirilsin" ko'rsatmalari, yangi tahrir esa asosiy
qonun matnida allaqachon bor. Ular bazada qoladi va `--include-amending` bilan qidiriladi.

Embedding tezligi (Intel i7-8750H, ONNX, batch=1): ~360 token/s, ya'ni chunkiga ~0.6 s.
Batchni oshirish bu CPU'da sekinlashtiradi (padding va xotira).

`index` ham checkpoint bilan ishlaydi: indeksda bor va matni o'zgarmagan chunklar qayta hisoblanmaydi.
Boshqa modelga o'tish uchun `data/index/chroma` ni o'chiring.

### Tezroq: embedding Google Colab GPU'da (sifat bir xil)

Mac CPU'da ~11 soat, Colab T4 GPU'da ~30-60 daqiqa. Model, pooling va fp32 aniqlik bir xil.

```bash
python -m lexrag export-colab        # -> data/colab/embed_input.jsonl.gz (~11 MB)
```
1. https://colab.research.google.com -> File -> Upload notebook -> `colab/embed_bge_m3.ipynb`
2. Runtime -> Change runtime type -> T4 GPU
3. Hujayralarni ketma-ket ishga tushiring, so'ralganda `embed_input.jsonl.gz` ni yuklang
4. Yuklab olingan `vectors.npz` ni `data/colab/` ga qo'ying

```bash
python -m lexrag import-vectors data/colab/vectors.npz
```
Import oldidan 24 ta tasodifiy chunk shu Mac'da ONNX bilan qayta hisoblanib, Colab vektorlari bilan
solishtiriladi; cosine 0.999 dan past bo'lsa import qilinmaydi.

## Veb-ilova "Dalil"

FastAPI backend (`lexrag/web/app.py`) + Vite/React/TypeScript frontend (`web/`). Frontend yig'ilgach
(`web/dist`) uni FastAPI o'zi beradi, shuning uchun ilova bitta buyruq bilan ishlaydi. Oddiy brauzerda
(desktop: 3 ustun, telefon: iOS uslubidagi varaqlar) va Telegram Mini App ichida ochiladi.

Bir marta o'rnatish (Node.js 20+ kerak):

```bash
cd "/Users/dilshodsbook/Documents/SecondBrain/General tasks/lexuz-rag"
.venv/bin/pip install -r requirements.txt     # fastapi, uvicorn qo'shildi
cd web && npm install && npm run build && cd ..   # -> web/dist
```

Ishga tushirish (loyiha papkasidan):

```bash
.venv/bin/python -m uvicorn lexrag.web.app:app --port 8000
```

Keyin brauzerda http://127.0.0.1:8000 oching. Birinchi ishga tushishda bge-m3 modeli va BM25 indeksi
xotiraga yuklanadi (~7 s), so'ng har savolga javob ~10-30 s (asosan LLM). To'xtatish: terminalda `Ctrl+C`.

Frontend ustida ishlash (o'zgarishlar darhol ko'rinadi): bir terminalda yuqoridagi uvicorn buyrug'i,
ikkinchisida `cd web && npm run dev` va http://localhost:5173 (`/api` 8000-portga yo'naltiriladi).

API:

| Yo'l | Nima qiladi |
|---|---|
| `POST /api/ask` | Server kaliti bilan (bepul limit). `{"question": "...", "filters": {"only_active": true, "include_amending": false, "doc_types": ["Qonun","Kodeks","Konstitutsiya"]}, "lang": "auto", "mode": "legal"}` -> SSE oqim: `step` (bosqichlar), `sources`, `delta` bo'laklari, `followups`, `quota`, oxirida `done` (yoki `error`: `free_limit`, `no_key`, `bad_key`, `quota`, `timeout`, `busy`, `network`, `llm`). Sodda rejim: `"mode": "simple", "chunk_ids": [...], "base_answer": "..."` |
| `POST /api/context` | O'z kaliti uchun: o'sha body -> `{steps, sources, no_answer, lang, parts, post: {marker, translit}, prompt: {system, user}}`. LLM'ni brauzer foydalanuvchi kaliti bilan o'zi chaqiradi, javobni `post` qoidasi bo'yicha qayta ishlaydi |
| `POST /api/verify` | Ishonch tekshiruvi, LLM'siz: `{"text": "...", "chunk_ids": [...], "lang": "uz", "mode": "legal"}` -> `{level: high/medium/low, checked, supported, claims: [{start, end, ok, reasons}]}` |
| `GET /api/quota` | Bugungi bepul savollar: `{free, limit, used, left, reason}` |
| `POST /api/proxy/openai/chat/completions` | Faqat OpenAI uchun o'tkazgich (pastda sababi). Kalit `Authorization` sarlavhasida keladi, saqlanmaydi |
| `GET /api/search?q=...&k=8&only_active=true&include_amending=false&types=Kodeks` | faqat qidiruv, LLM'siz |
| `GET /api/health` | indeks va LLM holati (kalitning o'zi qaytarilmaydi) |
| `GET /api/stats` | hujjatlar, chunklar soni, baza sanasi (report.md va indeksdan) |
| `GET /api/docs` | Swagger |

LLM (server kaliti): `.env` dagi `LLM_PROVIDER` va kalit. Gemini standart modeli `gemini-3.1-flash-lite`
(bepul tarifda limiti kattaroq); 503/429, 404 yoki timeout bo'lsa `gemini-3.5-flash`, `gemini-3.8-flash`,
`gemini-flash-latest` zaxiralariga o'tadi. `.env` da kalit bo'lmasa ilova ishlayveradi: manbalar topiladi,
javob uchun foydalanuvchiga o'z kalitini ulash taklif qilinadi.

### AI ulash: o'z kaliti va bepul sinov

Har foydalanuvchi o'z AI hisobidan foydalanadi, server kaliti esa faqat qisqa bepul sinov uchun.

* **Bepul sinov.** Kaliti yo'q foydalanuvchi kuniga `FREE_DAILY_LIMIT` ta savol beradi (server kaliti bilan).
  Hammaga birgalikda kuniga `GLOBAL_DAILY_LIMIT` ta (Gemini bepul tarifi har model uchun kuniga ~20 so'rov).
  Foydalanuvchi: Telegram Mini App'da `initData` dagi `user.id` (`TELEGRAM_BOT_TOKEN` bo'lsa imzo HMAC bilan
  tekshiriladi), aks holda brauzerdagi qurilma ID + IP (IP'ga 4 barobar limit: localStorage'ni tozalab cheksiz
  savol olib bo'lmaydi). Hisoblagich `data/state/quota.sqlite` da, ID va IP xeshlangan, kun Toshkent vaqti bilan.
  Faqat LLM haqiqatan chaqirilgan savol hisoblanadi; "topilmadi" (LLM'siz) va LLM xatosi hisoblanmaydi.
* **O'z kaliti (BYOK).** Sozlamalar -> "AI ulash": Gemini, OpenAI yoki Claude, kalit, model, "Tekshirish"
  (bir necha tokenlik sinov so'rovi). Kalit faqat foydalanuvchi qurilmasida: localStorage, Telegram ichida
  `Telegram.WebApp.CloudStorage` ham. Server faqat manbalar va tayyor so'rovni beradi (`/api/context`),
  LLM'ni brauzer o'zi chaqiradi:
  * Gemini (`streamGenerateContent?alt=sse`, kalit `x-goog-api-key` sarlavhasida) va Claude
    (`anthropic-dangerous-direct-browser-access: true`) - to'g'ridan-to'g'ri, kalit serverga umuman kelmaydi.
  * OpenAI - `/api/proxy/openai` orqali: OpenAI xato javoblarida (401/429) CORS sarlavhasi yo'q, brauzer
    "noto'g'ri kalit"ni "internet yo'q"dan ajrata olmaydi. Kalit faqat so'rov sarlavhasida o'tadi: faylga,
    logga yozilmaydi (`scripts/byok_e2e.py` server logini ham tekshiradi).

`.env` sozlamalari (`.env.example` da):

```bash
FREE_DAILY_LIMIT=5           # bitta foydalanuvchiga kuniga savol
GLOBAL_DAILY_LIMIT=100       # hammaga birgalikda kuniga savol (0 = bepul rejim o'chiq)
TELEGRAM_BOT_TOKEN=          # ixtiyoriy: Mini App foydalanuvchisi initData imzosi bilan aniqlanadi
```

**HTTPS shart.** Internetga chiqarilganda ilova faqat HTTPS orqali berilsin (cloudflared, nginx + Let's Encrypt):
oddiy HTTP'da OpenAI kaliti (proksi sarlavhasi) va savollar tarmoqda ochiq ketadi, Telegram Mini App esa
faqat HTTPS manzilni qabul qiladi. Server cloudflared/nginx ortida (127.0.0.1 dan) bo'lsa, foydalanuvchi
IP'si `CF-Connecting-IP` / `X-Forwarded-For` dan olinadi; tashqaridan to'g'ridan kelgan so'rovda bu sarlavhalarga
ishonilmaydi.

Sinov va skrinshotlar (server ishlab turganda):

```bash
.venv/bin/python scripts/web_smoke.py                 # 5 ta savol oxirigacha (SSE), natija terminalda
.venv/bin/pip install playwright && .venv/bin/python -m playwright install chromium
.venv/bin/python scripts/shots.py --out design/shots/app   # desktop 1440px va telefon 390px
```

"AI ulash" va bepul limit sinovi (alohida 8010-portdagi serverni o'zi ishga tushiradi va to'xtatadi; frontend
`web/dist` emas, vaqtinchalik papkaga yig'iladi, shuning uchun ishlab turgan asosiy serverga tegmaydi):

```bash
.venv/bin/python scripts/test_quota.py                     # limit va Telegram HMAC, LLM'siz
cd web && npx vite build --outDir /tmp/dalil-byok-dist --emptyOutDir && cd ..
.venv/bin/python scripts/byok_e2e.py --fresh-quota         # limit=2; server kaliti bilan 2 ta haqiqiy savol
.venv/bin/python scripts/byok_e2e.py --only api,keys,byok,mock,tg   # LLM sarflamasdan
```

### 2-bosqich: bosqichli qidiruv, javob tili, sodda rejim, ulashish, ishonch

Har funksiya ikkala yo'lda ishlaydi: server kaliti (`/api/ask` SSE) va o'z kaliti (`/api/context` + brauzerdan LLM).
Promptlar bitta joyda - `lexrag/rag.py` (`system_prompt(lang, mode)`); frontend faqat parametr yuboradi.

* **Bosqichlar.** `rag.prepare_steps` - generator: "Savol tahlil qilinmoqda -> Qidirilmoqda -> N ta modda topildi ->
  Tekshirilmoqda", brauzer "Javob yozilmoqda"ni qo'shadi. Ekranda bittadan ochiladi, tugagach "5 bosqich · 2,5 s"
  satriga yig'iladi (bosilsa ochiladi). Murakkab savol LLM'siz evristika bilan (`lexrag/plan.py`: bir nechta "?",
  "va" / "hamda" bilan bog'langan ikki savol qismi) 2-3 qidiruvga bo'linadi, to'liq savol ham qidiriladi, natijalar RRF
  bilan birlashadi, takrorlar olib tashlanadi. LLM bilan bo'lish faqat `.env` da `LLM_PLAN=1` va so'rovda
  `"llm_plan": true` bo'lsa (standart o'chiq: bepul tarif kuniga ~20 so'rov).
* **Javob tili** (`lexrag/lang.py`). Savoldan avtomatik: lotin -> lotin; kirill (ў қ ғ ҳ yoki o'zbekcha so'zlar) ->
  LLM lotinda yozadi, `translit.lat_to_cyr` kirillga o'giradi ([n], raqam, havola, rim raqamlari o'zgarmaydi; oqimda
  faqat to'liq so'zlar o'giriladi); rus -> LLM'ga ruscha javob ko'rsatmasi, manba kartochkalari asl o'zbekcha.
  Ruscha savolda dense qidiruv asl ruscha matn bilan (bge-m3 ko'p tilli: "развод" endi Oila kodeksini topadi),
  BM25 ga kichik lug'atdan o'zbekcha atamalar beriladi, og'irligi kamaytiriladi. Filtrlar oynasida
  "Javob tili: Avto / Oʻzbekcha / Ўзбекча / Русский"; interfeys tili o'zgarmaydi.
* **Keyingi savollar** qo'shimcha LLM so'rovisiz: LLM javob oxirida `<<<KEYINGI>>>` dan keyin 3 ta savol yozadi.
  Ajratgich va undan keyingi qism oqimda ko'rinmaydi (bo'laklar orasida uzilsa ham). Parser serverda
  (`lang.FollowupSplitter`) va brauzerda (`web/src/textproc.ts`) bir xil; `scripts/test_stage2.py` ikkalasini node
  bilan bir xil misollarda solishtiradi. Chip bosilsa - shu suhbatda yangi savol.
* **Sodda qilib tushuntir.** O'sha savol + o'sha manbalar (`chunk_ids`, tartib saqlanadi - [n] o'zgarmaydi), qayta
  qidiruvsiz, kundalik misol bilan. Javob tepasida "Yuridik / Sodda" almashtirgich - ikkalasi saqlanadi, qayta so'rov yo'q.
* **Ulashish.** Telefonda `navigator.share` (matn + 1080x1350 PNG rasm-kartochka, Web Share Level 2 bo'lsa). Kompyuterda,
  tizim oynasi bo'lmasa va Telegram Mini App ichida - menyu: Telegram (`t.me/share/url`, Mini App'da
  `Telegram.WebApp.openTelegramLink`), WhatsApp (`wa.me`), matnni nusxalash, rasmni yuklab olish. Rasm canvas'da
  chiziladi (`web/src/share.ts`): savol, javobning boshi, 1-3 manba (hujjat + modda), "lex.uz manbasi asosida · Bu
  yuridik maslahat emas". Matn: savol + javob + manba havolalari + sayt.
* **Ishonch** (`lexrag/trust.py`, `POST /api/verify`), LLM'siz. Javob gaplarga bo'linadi; har da'vo iqtibos qilingan
  modda bilan solishtiriladi: raqam va muddatlar manbada bormi (so'z bilan yozilganlari ham: "yigirma bir" = 21),
  so'zlar mosligi va bge-m3 o'xshashligi. Natija: "Ishonch: Yuqori / O'rta / Past", bosilsa izoh (nechta da'vo
  tekshirildi, qaysi gap asossiz ko'rindi va nega); o'sha gap matnda nuqtali chiziq bilan belgilanadi. Chegaralar
  qo'lda yozilgan to'g'ri va ataylab buzilgan javoblarda tanlangan. Sodda javobdagi misol va maslahatlar tekshirilmaydi.

Sinov (LLM'siz qismlar istalgancha, real bosqich har ishga tushishda ~7 ta LLM so'rovi sarflaydi):

```bash
.venv/bin/python scripts/test_stage2.py              # translit, til, ajratgich, bo'lish, brauzer=server, trust
cd web && npx vite build --outDir /tmp/dalil-s2-dist --emptyOutDir && cd ..
.venv/bin/python scripts/test_server.py --port 8010 --free-limit 30 --dist /tmp/dalil-s2-dist --quota-db /tmp/dalil-s2-quota.sqlite
.venv/bin/python scripts/stage2_e2e.py --only api,mock          # LLM'siz (mock - brauzerda soxta provayder)
.venv/bin/python scripts/stage2_e2e.py --only real,reshoot,mobile   # haqiqiy LLM + skrinshotlar (design/shots/app/s2-*)
```

Yangi frontend backend o'zgarishlarisiz ishlamaydi (`step`, `/api/verify`): `web/dist` qayta yig'ilganda uvicorn ham
qayta ishga tushirilsin.

### 3-bosqich: X-ray (RAG ichi) va baholash

**X-ray.** Har javob ostida "Ichini koʻrish" tugmasi: desktopda o'ng panelda "Manbalar | Ichini koʻrish" tabi, telefonda
pastdan varaq. Ko'rsatiladi: savol tili/yozuvi, lotinga o'girilgan matn, bo'laklar; har qidiruv uchun dense (bge-m3,
cosine) va BM25 (ball) top-10, RRF birlashmasi (har manba qaysi usuldan: D / B / D+B, dense'ga nisbatan o'rin
o'zgarishi), `W_DENSE`, `W_BM25`, filtrlar, `NO_ANSWER_COS` va eng yaqin cosine; LLM'ga ketgan system va user prompt
(nusxalanadi, taxminiy token soni), model va provayder (server kaliti / o'z kaliti); vaqtlar waterfall'i (embedding,
dense, BM25, RRF, LLM birinchi token, oqim, umumiy); ishonch tekshiruvining har gapi (qaysi manba, ma'no o'xshashligi,
so'zlar mosligi). Ma'lumot qo'shimcha LLM so'rovisiz yig'iladi:

* `/api/ask` va `/api/context` body'sida `"xray": true` -> SSE'da alohida `xray` hodisasi (`done` da LLM vaqtlari
  `xray_llm`), o'z kaliti yo'lida `/api/context` javobida `xray` (LLM vaqtini brauzer o'lchaydi). `xray` yo'q bo'lsa
  hech narsa ortiqcha hisoblanmaydi (`retrieval.hybrid_search(trace=None)`).
* Sozlamalar / filtrlar oynasida "X-ray rejimi" — yoqilsa har savolda yig'iladi va panel o'zi ochiladi. O'chiq bo'lsa ham
  tugma ishlaydi: qidiruv LLM'siz qayta bajariladi (bu ekranda aytiladi).

**Baholash.** `eval/questions.jsonl` — 50 savol (46 tasi gold modda bilan, 4 tasi bazada yo'q; 34 lotin, 9 kirill,
7 rus), metodika `eval/README.md` da.

```bash
.venv/bin/python -m lexrag eval                             # dense, bm25, hybrid, hybrid_plan + sweep (~40 s, LLM'siz)
.venv/bin/python -m lexrag eval --modes dense,hybrid --k 10 --no-sweep
.venv/bin/python scripts/eval_answers.py                    # ixtiyoriy: 5 savol javob sifati (5 ta LLM so'rovi)
```

Natija: `eval/results.json` (har savol tafsiloti bilan), `eval/results.md` (jadvallar), `eval/sweep.json`
(`W_BM25` va `NO_ANSWER_COS`). Veb-ilovada `/baholash` sahifasi (yon panelda "Baholash", telefonda menyu -> Sozlamalar):
KPI, rejimlar taqqoslash, recall@k egri chizig'i, kategoriya/til/qiyinlik kesimlari, sweep grafiklari, har savol jadvali
("faqat xatolar" filtri, qator bosilsa — gold modda qaysi rejimda nechanchi o'rinda). "Qayta hisoblash" —
`POST /api/eval/run` (fon vazifa, bir vaqtda bitta, progress `GET /api/eval/status`; `.env` da `EVAL_TOKEN=...`
bo'lsa `X-Eval-Token` sarlavhasi talab qilinadi).

Sweep natijasida standartlar o'zgardi: `W_BM25` 0.6 -> 0.05 (gibrid recall@5 61.2% -> 83.7%), `NO_ANSWER_COS`
0.45 -> 0.48. Sababi va raqamlar `eval/README.md` va `report.md` da.

Sinov (alohida 8010-port serveri, `web/dist` ga tegmaydi):

```bash
cd web && npx vite build --outDir /tmp/dalil-s3-dist --emptyOutDir && cd ..
.venv/bin/python scripts/test_server.py --port 8010 --free-limit 30 --dist /tmp/dalil-s3-dist \
    --quota-db /tmp/dalil-s3-quota.sqlite --llm-once        # --llm-once: savolga aynan 1 ta LLM so'rovi
.venv/bin/python scripts/stage3_e2e.py --only api,mock,reshoot,eval   # LLM'siz
.venv/bin/python scripts/stage3_e2e.py --only real                    # 2 ta haqiqiy LLM so'rovi + skrinshotlar
```

Skrinshotlar: `design/shots/app/s3-*.png`.

Telegram Mini App: BotFather'da botga Web App URL sifatida ilovaning HTTPS manzilini bering (masalan,
`cloudflared tunnel --url http://127.0.0.1:8000` bergan manzil). Ilova `telegram-web-app.js` orqali
Telegram temasi, safe-area, viewport balandligi va "orqaga" tugmasini o'zi hisobga oladi.

## Tuzilma

```
lexrag/
  config.py     URL, papkalar, pauza, chunk hajmlari
  http.py       PoliteClient: 1-2 s pauza, retry, exponential backoff, Retry-After
  scraper.py    ro'yxat (postback) + hujjat/kartochka yuklash, checkpoint, failures.jsonl
  normalize.py  Unicode NFC, oʻ/gʻ -> U+02BB, tutuq -> U+02BC, bo'sh joylar
  parser.py     raw HTML -> data/clean/<id>.json, metadata.csv
  chunker.py    Bo'lim > Bob > Modda bo'yicha chunklar (bge-m3 tokenizatori)
  verify.py     saytdagi jonli matn bilan so'zma-so'z solishtirish
  report.py     report.md, data/missing.csv
  indexer.py    fastembed + ChromaDB
  search.py     savol -> top-k chunk manbasi bilan
  retrieval.py  gibrid qidiruv: bge-m3 (dense) + BM25, Reciprocal Rank Fusion
  translit.py   kirill <-> lotin (savol lotinga, kirill savolga javob kirillga)
  lang.py       til aniqlash, <<<KEYINGI>>> keyingi savollar parseri, ruscha BM25 lug'ati
  plan.py       murakkab savolni 2-3 qidiruvga bo'lish (evristika; LLM_PLAN=1 bilan LLM)
  trust.py      ishonch tekshiruvi: javob da'volari vs iqtibos qilingan moddalar (LLM'siz)
  llm.py        Gemini / OpenAI / Claude (HTTP, streaming)
  rag.py        bosqichlar, promptlar (yuridik / sodda, til), manbali javob: [n] iqtiboslar, "topilmadi" himoyasi, X-ray
  evaluate.py   qidiruv sifatini baholash (eval/), recall@k, MRR, nDCG, rad etish, sweep
  colab.py      embeddingni Colab GPU'da hisoblash: eksport/import + sifat tekshiruvi
  web/app.py    FastAPI: /api/ask (SSE), /api/context, /api/verify, /api/quota, /api/search, /api/health, /api/stats,
                /api/eval (+ /run, /status) + web/dist
  web/quota.py  bepul limit: foydalanuvchini aniqlash (Telegram HMAC / qurilma + IP), SQLite hisoblagich
web/            React frontend (src/App.tsx, ai.ts - o'z kaliti bilan LLM, textproc.ts - javob oqimi parseri va translit,
                share.ts - ulashish va rasm-kartochka, components/, styles.css - A·Anor)
scripts/        web_smoke.py, shots.py, test_quota.py, byok_e2e.py, test_server.py (sinov serveri), test_stage2.py, stage2_e2e.py,
                stage3_e2e.py, eval_answers.py
eval/           questions.jsonl (baholash to'plami), README.md (metodika), results.json/.md, sweep.json, baseline_w06.json, answers.json
data/
  raw/list/       ro'yxat sahifalari HTML
  raw/docs/       hujjat HTML (<lex_id>.html)
  raw/cards/      rekvizitlar kartochkasi HTML
  clean/<id>.json tozalangan hujjat (id = lex_id ning moduli, masalan -6257288 -> 6257288)
  chunks.jsonl    barcha chunklar
  metadata.csv    hujjatlar ro'yxati
  missing.csv     chiqmagan hujjatlar va sababi
  state/          list_index.jsonl, failures.jsonl, sample_ids.json, verify.json, quota.sqlite (bepul limit)
  index/chroma/   vektor baza
report.md
```

## Ma'lumot formati

`data/clean/<id>.json` asosiy maydonlari: `id, lex_id, title, doc_type, number, adoption_date,
issuing_body, status, entry_into_force_date, last_edition_date, url, language` + `text` (izohlarsiz toza
matn), `structure` (sarlavhalar va moddalar), `amendments` (o'zgartirish izohlari, qaysi moddaga tegishli),
`lexuz_notes`, `grif`, `signature`, `publication_source`, `classifiers`.

`status`: lex.uz'ning o'z uch toifasi - `amalda`, `kuchini yo'qotgan`, `amalda emas`.

`data/chunks.jsonl` har qatori: `chunk_id, doc_id, doc_title, doc_type, doc_number, adoption_date, status,
last_edition_date, article_number, article_title, section, chapter, heading, chunk_index, n_chunks_in_unit,
source_url` (moddaga to'g'ridan havola, `...#<element_id>`), `amendments, text` (sarlavha + matn), `body, n_tokens`.

## Chunking qoidalari

* Birlik - bitta modda; boshqa modda bilan aralashmaydi. Qisqa moddalar ham alohida qoladi: javobda aniq
  modda ko'rsatiladi va har chunk boshidagi kontekst sarlavhasi qisqa matnni ham ma'noli qiladi.
  Kerak bo'lsa `chunk --merge-short` bir bob ichidagi qisqa moddalarni ~300 tokengacha birlashtiradi.
* 800 tokendan uzun modda xatboshilar (qism/band) bo'yicha teng bo'laklarga bo'linadi, har bo'lak
  oldingisining oxirgi xatboshisini (~80 token) overlap sifatida oladi.
* Sarlavha: `<Hujjat nomi (turi, raqami, sanasi)> > <Bo'lim> > <Bob> > N-modda. Sarlavha [i/n-bo'lak]`.
* O'zgartirish qonunlarida boshqa qonunga kiritilayotgan iqtibos moddalar ("75¹-modda ...") alohida modda
  hisoblanmaydi, ota moddaning matnida qoladi (modda raqami ketma-ketligi bo'yicha aniqlanadi).
