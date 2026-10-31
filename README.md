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
python -m lexrag search "Mikromoliya tashkiloti bankka aylanishi mumkinmi?" -k 5   # gibrid: bge-m3 + BM25
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
  translit.py   kirillcha savolni lotinga o'girish
  llm.py        Gemini / OpenAI / Claude (HTTP, streaming)
  rag.py        manbali javob: [n] iqtiboslar, "topilmadi" himoyasi
  colab.py      embeddingni Colab GPU'da hisoblash: eksport/import + sifat tekshiruvi
data/
  raw/list/       ro'yxat sahifalari HTML
  raw/docs/       hujjat HTML (<lex_id>.html)
  raw/cards/      rekvizitlar kartochkasi HTML
  clean/<id>.json tozalangan hujjat (id = lex_id ning moduli, masalan -6257288 -> 6257288)
  chunks.jsonl    barcha chunklar
  metadata.csv    hujjatlar ro'yxati
  missing.csv     chiqmagan hujjatlar va sababi
  state/          list_index.jsonl, failures.jsonl, sample_ids.json, verify.json
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
