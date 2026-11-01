# Baholash to'plami (qidiruv sifati)

```bash
python -m lexrag eval                                   # hamma rejimlar + sweep -> results.json, results.md, sweep.json
python -m lexrag eval --modes dense,hybrid --k 10       # faqat tanlangan rejimlar
python -m lexrag eval --no-sweep
```

LLM chaqirilmaydi: faqat qidiruv o'lchanadi (bitta to'liq ishga tushirish ~40 s, Intel i7 CPU). Natijalar veb-ilovada
`/baholash` sahifasida ham ko'rinadi, u yerdan "Qayta hisoblash" bilan qayta ishga tushiriladi (`POST /api/eval/run`).

## To'plam qanday tuzilgan

`questions.jsonl` — **170 ta savol** (4-bosqichda 50 → 170): 161 tasining javobi bazada bor, 9 tasi ataylab bazada
yo'q — umumiy savollar (palov, futbol, Wi-Fi, smartfon), chet el qonunlari (Germaniya nafaqasi, Rossiya ta'tili, AQSh
guvohnomasi, Qozog'iston pensiyasi) va qonunda belgilanmaydigan narx (metro yo'l haqi).

| Yozuv / til | javobli | "bazada yo'q" | DEV / TEST |
|---|---|---|---|
| o'zbek lotin | 111 | 5 | 58 / 58 |
| o'zbek kirill | 30 | 2 | 16 / 16 |
| rus | 20 | 2 | 11 / 11 |

25 kategoriya: mehnat 24, fuqarolik 12, jinoyat 13, oila 11, konstitutsiya 10, soliq 9, ijtimoiy 9, ma'muriy 8, saylov 7,
tadbirkorlik 7, transport 6, ta'lim 5, sog'liq 5, uy-joy, iste'molchi, bank, bojxona 4 tadan, yer, intellektual mulk,
migratsiya, harbiy, axborot, boshqa 3 tadan, notariat 1. Qiyinlik: oson 61, o'rta 67, qiyin 42.

Har savolda `lang` (haqiqiy til; kesimlar shu bo'yicha, ilova aniqlagan til natijada `lang_detected`), `split` va yangi
savollarda `evidence` (gold moddadan qisqa iqtibos — yozuvchi moddani o'qiganini tekshirish uchun).

**DEV / TEST.** `split`: 85 / 85, tasodifiy (seed 20261101), (kategoriya, til) qatlamlari bo'yicha muvozanatli
(`scripts/build_eval_set.py`). Barcha sozlash — W_BM25 va NO_ANSWER_COS sweep, ishonch chegaralari, stemmer va
stopword variantlari — faqat DEV'da; TEST faqat yakuniy raqamlar uchun (`sweep.json` da TEST jadvali ham bor, lekin
"best" DEV bo'yicha tanlanadi).

Qanday yozildi (3-bosqich, 50 savol — bir kishi; 4-bosqich, 120 savol — Claude yordamchi agentlari, xuddi shu qoidalar
bilan; Gemini va qidiruv tizimi ishlatilmadi). Kirillning bir qismi ataylab rus klaviaturasida (у/к/х/г o'rniga
ў/қ/ҳ/ғ, ъ tushirib), lotinning bir qismi apostrofsiz yoki "g`" bilan — real foydalanuvchilar kabi:
1. Avval modda tanlandi: kodeks/qonun moddalari sarlavhalari bo'yicha ko'rib chiqildi, matni (`data/chunks.jsonl`)
   to'liq o'qildi. Moddani tanlashda qidiruv tizimining o'zi ishlatilmadi — aks holda to'plam tizimga moslashib qolardi.
2. Savol modda matnidan ko'chirilmay, oddiy odam so'raydigan tilda yozildi: "dastlabki sinov muddati uch oydan
   oshmasligi kerak" -> "Ishga olishda sinov muddati eng ko'pi bilan qancha bo'lishi mumkin?". Shuning uchun BM25 (so'z
   mosligi) bu to'plamda sun'iy ustunlikka ega emas — real foydalanuvchi savollariga yaqin.
3. Gold = `doc_id` + modda raqami. Uzun modda bir nechta bo'lakka bo'lingan bo'lsa, istalgan bo'lagi to'g'ri hisoblanadi.
   Javobi ikki moddada bo'lsa (masalan, Prezident yoshi: Konstitutsiya 106 va Saylov kodeksi 61) ikkalasi gold.
4. Har ishga tushirishda `check_gold` har gold moddaning bazada borligini va standart filtrdan (amaldagi hujjat,
   o'zgartirish qonuni emas) o'tishini tekshiradi; mavjud bo'lmagan modda bo'lsa baholash to'xtaydi.
5. Qiyinlik: oson — savol so'zlari moddaga yaqin; o'rta — sinonimlar bilan; qiyin — hayotiy vaziyat orqali
   ("Xotinim homilador, ajrashish uchun ariza bera olamanmi?") yoki ikki qismli savol (bo'lish rejimini sinash uchun).

Cheklovlar: TEST'da 80 ta javobli savol — 1 savol ≈ 1.25 foiz punkt, ~3 punktdan kichik farq shovqin chegarasida.
Yangi savollarni bitta model oilasi yozgan (uslub bir xilligi). "Bazada yo'q" savollar 9 ta — rad etish bo'yicha xulosa
taxminiy.

## Metrikalar

* **recall@k** — gold moddalarning qancha qismi qidiruvning birinchi k natijasida bor (bitta gold bo'lsa = hit@k).
  Asosiy ko'rsatkich recall@5: ilova LLM'ga 8 ta modda beradi, to'g'ri modda yuqorida bo'lishi kerak.
* **MRR@10** — birinchi to'g'ri moddaning o'rni: 1-o'rin = 1, 2-o'rin = 0.5, ... 10 dan keyin = 0.
* **nDCG@10** — bir nechta gold bo'lsa hammasining o'rnini hisobga oladi (binar relevantlik).
* **Rad etish** — "bazada yo'q" savolda LLM chaqirilmasligi: ilovadagi qoida bilan bir xil, LLM'ga boradigan 8 ta
  manbaning eng yuqori cosine'i `NO_ANSWER_COS` dan past bo'lsa "topilmadi". Alohida sanaladi: to'g'ri rad etilgan
  "yo'q" savollar va xato rad etilgan (javobi bor) savollar.
* **Vaqt** — bitta savol qidiruvi (embedding + ChromaDB + BM25 + RRF), model xotiraga yuklangandan keyin.

Rejimlar: `dense` (bge-m3 + ChromaDB), `bm25`, `hybrid` (RRF: `W_DENSE/(60+r) + W_BM25/(60+r)`), `hybrid_plan`
(murakkab savol `plan.split_question` bilan bo'linadi, qismlar alohida qidiriladi va RRF bilan birlashadi — ilovadagi
`rag.prepare_steps` bilan bir xil). Baholash ilovadagi funksiyalarning o'zini chaqiradi (`retrieval.rrf`,
`dense_search`, `bm25_search`, `rag._fuse`), alohida nusxa emas.

## Natija va standartlar o'zgarishi

Birinchi ishga tushirish (eski standart `W_BM25 = 0.6`, `NO_ANSWER_COS = 0.45`, `baseline_w06.json`):

| Rejim | R@1 | R@5 | R@10 | MRR@10 |
|---|---|---|---|---|
| Dense | 57.2% | 81.5% | 88.0% | 0.733 |
| BM25 | 14.1% | 22.5% | 27.9% | 0.200 |
| Gibrid, W_BM25 = 0.6 | 35.5% | 61.2% | 79.3% | 0.509 |

Gibrid dense'dan **yomonroq** chiqdi. Sabab (`results.json` dagi har savol tafsilotida ko'rinadi): parafrazali savolda
BM25 umumiy so'zlarga ("uchun", "qanday", "necha", "kerak") ball beradi; RRF ikkala ro'yxatda o'rtacha o'rinda
turgan moddalarni (masalan, dense 12-o'rin + BM25 11-o'rin) dense'ning 2-o'rnidagi to'g'ri moddadan yuqoriga chiqaradi.

`W_BM25` sweep (`sweep.json`): og'irlik kamaygan sari sifat oshadi; recall@5 bo'yicha eng yaxshisi **0.05**
(83.7%), MRR@10 bo'yicha sof dense (0.0: 0.733, 0.05 da 0.716). 0.05 tanlandi: asosiy ko'rsatkich recall@5 va BM25
aniq atamalar (modda nomi, "aliment") uchun yengil qo'shimcha bo'lib qoladi. Ruscha savollarning BM25 og'irligi ham
endi `W_BM25` ga nisbatan (×0.75 / ×0.25, avval 0.45 / 0.15 qat'iy edi).

| | oldin (0.6) | keyin (0.05) |
|---|---|---|
| Gibrid recall@5 | 61.2% | 83.7% |
| Gibrid recall@1 | 35.5% | 55.1% |
| Gibrid MRR@10 | 0.509 | 0.716 |
| Gibrid + bo'lish recall@5 | 59.4% | 83.0% |

`NO_ANSWER_COS`: javobi bor savollarda eng yaqin cosine 0.55 dan past emas, "yo'q" savollardan uchtasi 0.43–0.45.
0.46–0.54 oralig'ida natija bir xil (3/4 to'g'ri rad, 0/46 xato rad). Eski 0.45 ham shu natijani berardi, lekin bitta
"yo'q" savol 0.448 da — chegaraga juda yaqin. Standart **0.48** qilindi (ikki guruh orasining o'rtasiga yaqin).
To'rtinchi "yo'q" savol (Germaniyadagi ishsizlik nafaqasi, cosine 0.61) O'zbekistonning nafaqa haqidagi moddalariga
ma'no jihatdan yaqin: uni cosine chegarasi bilan rad etib bo'lmaydi (0.62 da 14 ta to'g'ri savol ham rad bo'ladi).
Bunday savolni LLM o'zi "manbalarda javob yo'q" deb aytishi kerak (system prompt 4-qoida).

Hozirgi raqamlar: `results.md`. Fayllar: `results.json` (har savol: gold, har rejimdagi o'rni, top-5, dense/BM25
ro'yxatidagi o'rni), `sweep.json`, `baseline_w06.json` (o'zgarishdan oldingi qisqa natija), `answers.json`
(ixtiyoriy javob sifati, pastda).

## 4-bosqich: zaif joylarni tuzatish (oldin/keyin)

Fayllar: `baseline_stage3.json` (3-bosqich natijasi, eski 50 savol), `baseline_v2.json` (3-bosqich kodi yangi 170 savolda —
"oldin"), `tuning_stage4.json` (DEV'dagi variantlar, `scripts/tune_stage4.py`), `trust_calibration.json` (ruscha ishonch
kalibrlash, `scripts/calibrate_trust.py`), `answers_ru.json` (6 ta haqiqiy ruscha LLM javobi), `results.*` va `sweep.json` —
"keyin". Oldin/keyin jadvali, sabablar va cheklovlar: `results.md` va `report.md` (6-bo'lim).

DEV'da tanlangan qarorlar (raqamlar `tuning_stage4.json` da):

| Qaror | Variantlar (DEV) | Tanlangan |
|---|---|---|
| Kirill: so'z tiklash | o'chiq / dense+BM25 / faqat BM25 | faqat BM25 (dense'ga berish kirill R@5 85.6% → 78.9%) |
| Kirill: dense matni | lotin / lotin + asl kirill (RRF) | lotin (asl kirill qo'shilsa 85.6% → 72.2%) |
| BM25 tokenizatori | 7 harf / stem / stem + so'z yasovchi; stopword: yo'q / asosiy / + huquqiy | stem + asosiy stopwordlar (BM25 R@5 38.1% → 43.6%) |
| Ruscha BM25 | lug'at + translit / faqat lug'at / o'chiq | o'chiq (gibrid teng, MRR 0.689 ≥ 0.688) |
| W_BM25 | 0 … 2.0 | 0.05 (o'zgarmadi) |
| NO_ANSWER_COS | 0.30 … 0.70, mezon: xato rad ≤ 1% bilan eng ko'p to'g'ri rad | 0.48 (o'zgarmadi; 0.46–0.52 teng) |
| Ishonch, ruscha | COS_OK_RU 0.50 … 0.66, sonli da'vo chegarasi, ro'yxat konteksti; Youden J | 0.58, sonli 0.52, kontekst bilan |

NO_ANSWER_COS mezoni o'zgardi: avval balanslangan aniqlik edi, lekin DEV'da 4 ta "yo'q" savol bilan u 0.62 ni tanlaydi —
javobi bor savollarning 32% i "topilmadi" bo'lib qoladi. Ilovada bu LLM'ni ortiqcha chaqirishdan ancha qimmat.

Ruscha ishonch kalibrlash ma'lumoti: 7 ta haqiqiy ruscha javob (r01 + 6 ta yangi; har da'vo manba bilan qo'lda
solishtirildi — hammasi to'g'ri), o'zbekcha javoblarning (q02, q14, q28, c03) qo'lda ruscha tarjimasi, 17 ta ataylab
noto'g'ri ruscha da'vo (mavzu to'g'ri, mazmun/son noto'g'ri) va ularning o'zbekcha varianti, hamda boshqa savol manbasiga
bog'langan da'volar. Maqsad — ruscha tekshiruv o'zbekcha bilan teng qattiqlikda bo'lsin: o'zbekcha qoidalar 17 ta yolg'on
da'voning 6 tasini o'tkazadi, yangi ruscha chegaralar ham 6 tasini.

## Javob sifati (ixtiyoriy, LLM bilan)

`scripts/eval_answers.py` — 5 ta savol bo'yicha haqiqiy LLM javobi: ishonch tekshiruvi bali (`/api/verify` mantig'i,
`trust.check`) va iqtibos to'g'riligi (javob gold moddani [n] bilan keltirganmi, [n] lar manbalar soni ichidami).
Jami 5 ta LLM so'rovi; limit (429) bo'lsa to'xtaydi va buni `answers.json` ga yozadi.
