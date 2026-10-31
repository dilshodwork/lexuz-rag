# Qidiruv sifatini baholash

Yaratilgan: 2026-11-01T01:43:26+05:00 · commit `afc2096` · 31.7 s

Savollar: 50 ta (46 tasining javobi bazada bor, 4 tasi bazada yo'q). Til: lotin 34, kirill 9, rus 7. Sozlamalar: W_DENSE=1.0, W_BM25=0.05, RRF_K=60, har usuldan 40 ta nomzod, NO_ANSWER_COS=0.48, filtr: faqat amaldagi, o'zgartirish qonunlarisiz. LLM chaqirilmagan.

## Asosiy natija

| Rejim | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | o'rtacha vaqt |
|---|---|---|---|---|---|---|---|
| Dense (bge-m3) | 57.2% | 74.3% | 81.5% | 88.0% | 0.733 | 0.750 | 489 ms |
| BM25 | 14.1% | 18.1% | 22.5% | 27.9% | 0.200 | 0.207 | 1 ms |
| Gibrid (RRF) | 55.1% | 69.9% | 83.7% | 88.0% | 0.716 | 0.738 | 490 ms |
| Gibrid + bo'lish | 54.4% | 69.2% | 83.0% | 88.0% | 0.702 | 0.730 | 564 ms |

## "Bazada yo'q" savollarni rad etish

Chegara NO_ANSWER_COS = 0.48 (LLM'ga beriladigan 8 ta manbaning eng yuqori cosine'i shundan past bo'lsa — "topilmadi").

| Rejim | to'g'ri rad etildi | noto'g'ri rad etildi (javobi bor savol) | aniqlik |
|---|---|---|---|
| Dense (bge-m3) | 3/4 | 0/46 | 98.0% |
| BM25 | — (cosine yo'q) | — | — |
| Gibrid (RRF) | 3/4 | 0/46 | 98.0% |
| Gibrid + bo'lish | 3/4 | 0/46 | 98.0% |

## Kategoriya bo'yicha recall@5

| Kategoriya | n | Dense (bge-m3) | BM25 | Gibrid (RRF) | Gibrid + bo'lish |
|---|---|---|---|---|---|
| mehnat | 12 | 79.2% | 6.9% | 79.2% | 76.4% |
| oila | 6 | 91.7% | 16.7% | 91.7% | 91.7% |
| fuqarolik | 6 | 66.7% | 16.7% | 75.0% | 75.0% |
| konstitutsiya | 5 | 100.0% | 30.0% | 100.0% | 100.0% |
| jinoyat | 5 | 80.0% | 40.0% | 80.0% | 80.0% |
| saylov | 3 | 83.3% | 33.3% | 100.0% | 100.0% |
| maʼmuriy | 3 | 66.7% | 33.3% | 66.7% | 66.7% |
| soliq | 3 | 66.7% | 33.3% | 66.7% | 66.7% |
| isteʼmolchi | 1 | 100.0% | 0.0% | 100.0% | 100.0% |
| ijtimoiy | 1 | 100.0% | 100.0% | 100.0% | 100.0% |
| tadbirkorlik | 1 | 100.0% | 0.0% | 100.0% | 100.0% |

## Til / yozuv bo'yicha recall@5

| Til / yozuv | n | Dense (bge-m3) | BM25 | Gibrid (RRF) | Gibrid + bo'lish |
|---|---|---|---|---|---|
| lotin | 32 | 84.4% | 29.2% | 87.5% | 86.5% |
| kirill | 8 | 68.8% | 0.0% | 68.8% | 68.8% |
| rus | 6 | 83.3% | 16.7% | 83.3% | 83.3% |

## Qiyinlik bo'yicha recall@5

| Qiyinlik | n | Dense (bge-m3) | BM25 | Gibrid (RRF) | Gibrid + bo'lish |
|---|---|---|---|---|---|
| o'rta | 20 | 72.5% | 17.5% | 75.0% | 75.0% |
| oson | 15 | 90.0% | 30.0% | 93.3% | 93.3% |
| qiyin | 11 | 86.4% | 21.2% | 86.4% | 83.3% |

## Sweep: W_BM25 (gibrid)

| W_BM25 | R@1 | R@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| 0.0 | 57.2% | 81.5% | 0.733 | 0.750 |
| 0.05 (joriy) | 55.1% | 83.7% | 0.716 | 0.738 |
| 0.1 | 48.5% | 77.2% | 0.671 | 0.704 |
| 0.2 | 36.6% | 75.0% | 0.574 | 0.631 |
| 0.3 | 37.7% | 64.5% | 0.563 | 0.625 |
| 0.4 | 35.5% | 61.2% | 0.531 | 0.589 |
| 0.6 | 35.5% | 61.2% | 0.509 | 0.559 |
| 0.8 | 33.3% | 61.2% | 0.490 | 0.539 |
| 1.0 | 33.3% | 56.9% | 0.483 | 0.528 |
| 1.5 | 30.1% | 45.3% | 0.419 | 0.441 |
| 2.0 | 25.7% | 43.1% | 0.388 | 0.417 |

Eng yaxshi (recall@5, teng bo'lsa MRR@10 bo'yicha): W_BM25 = 0.05. Ruscha savollarda BM25 og'irligi W_BM25 × 0.75 (lug'at atamasi bor) yoki × 0.25.

## Sweep: NO_ANSWER_COS

| chegara | to'g'ri rad | noto'g'ri rad | balanslangan aniqlik |
|---|---|---|---|
| 0.30 | 0/4 | 0/46 | 50.0% |
| 0.34 | 0/4 | 0/46 | 50.0% |
| 0.38 | 0/4 | 0/46 | 50.0% |
| 0.42 | 0/4 | 0/46 | 50.0% |
| 0.46 | 3/4 | 0/46 | 87.5% |
| 0.48 (joriy) | 3/4 | 0/46 | 87.5% |
| 0.50 | 3/4 | 0/46 | 87.5% |
| 0.54 | 3/4 | 0/46 | 87.5% |
| 0.58 | 3/4 | 6/46 | 81.0% |
| 0.62 | 4/4 | 14/46 | 84.8% |
| 0.66 | 4/4 | 27/46 | 70.7% |
| 0.70 | 4/4 | 40/46 | 56.5% |

Javobi bor savollarda eng yaqin cosine: min 0.5545, 10-persentil 0.6, mediana 0.65535. Bazada yo'q savollarda: 0.4315, 0.4439, 0.4481, 0.6102. Ikki guruh to'liq ajralmaydi.

## Xatolar (gibrid: gold modda top-5 da yo'q)

| id | savol | gold | gibrid o'rni | dense o'rni | BM25 o'rni |
|---|---|---|---|---|---|
| q01 | Ishchiga har yili kamida necha kun dam olish taʼtili berilishi kerak? | Mehnat kodeksi 217-m. | 9 | 9 | 19 |
| q06 | 17 yoshli o'smir ishlasa, unga yillik dam olish necha kun beriladi? | Mehnat kodeksi 418-m. | >10 | 22 | 32 |
| q17 | Odam necha yoshdan boshlab o'z nomidan har qanday bitim tuza oladi? | Fuqarolik kodeksi (1-qism) 22-m. | >10 | 16 | >40 |
| c06 | Бировнинг нарсасини яширинча олиб қўйгани учун қандай жазо бор? | Jinoyat kodeksi 169-m. | 7 | 7 | >40 |
| c07 | Кўчада бақириб сўкинган одамга қандай маъмурий жазо берилади? | Maʼmuriy javobgarlik toʻgʻrisidagi kodeks 183-m. | >10 | >40 | >40 |
| r06 | Какая ставка налога на добавленную стоимость в Узбекистане? | Soliq kodeksi 258-m. | >10 | 40 | >40 |
