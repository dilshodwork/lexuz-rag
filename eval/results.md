# Qidiruv sifatini baholash

Yaratilgan: 2026-11-01T14:58:08+05:00 · commit `122efa5` · 132.6 s · BM25 indeksi: `data/index/bm25`

Savollar: 170 ta (161 tasining javobi bazada bor, 9 tasi bazada yoʻq). Til: lotin 116, kirill 32, rus 22. Qismlar: DEV 85 (sozlash shu yerda), TEST 85 (yakuniy raqamlar). Sozlamalar: W_DENSE=1.0, W_BM25=0.05, RRF_K=60, har usuldan 40 ta nomzod, NO_ANSWER_COS=0.48, BM25 tokenizatori {'kind': 'stem', 'deriv': False, 'trunc': None}, soʻrov stopwordlari basic, ruscha BM25 off, soʻz tiklash bm25; filtr: faqat amaldagi, oʻzgartirish qonunlarisiz. LLM chaqirilmagan.

## Asosiy natija — TEST (80 javobli, 5 yoʻq)

| Rejim | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | o'rtacha vaqt |
|---|---|---|---|---|---|---|---|
| Dense (bge-m3) | 51.2% | 68.8% | 76.9% | 83.1% | 0.678 | 0.691 | 578 ms |
| BM25 | 23.8% | 36.9% | 42.5% | 51.9% | 0.350 | 0.380 | 1 ms |
| Gibrid (RRF) | 53.8% | 68.1% | 76.9% | 82.5% | 0.696 | 0.700 | 579 ms |
| Gibrid + bo'lish | 54.4% | 68.1% | 76.9% | 82.5% | 0.702 | 0.702 | 644 ms |

## Asosiy natija — DEV (81 javobli, 4 yoʻq)

| Rejim | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | o'rtacha vaqt |
|---|---|---|---|---|---|---|---|
| Dense (bge-m3) | 50.2% | 75.9% | 78.8% | 85.6% | 0.676 | 0.706 | 600 ms |
| BM25 | 18.3% | 35.6% | 43.6% | 51.2% | 0.335 | 0.362 | 1 ms |
| Gibrid (RRF) | 52.1% | 74.9% | 79.6% | 85.6% | 0.690 | 0.716 | 602 ms |
| Gibrid + bo'lish | 50.0% | 73.7% | 79.0% | 84.6% | 0.657 | 0.696 | 774 ms |

## Oldin / keyin (baseline_v2 — 3-bosqich kodi shu toʻplamda → hozir)

| Koʻrsatkich | TEST oldin | TEST keyin | farq | DEV oldin | DEV keyin | farq |
|---|---|---|---|---|---|---|
| Gibrid R@5 | 77.5% | 76.9% | -0.6 p.p. | 79.4% | 79.6% | +0.2 p.p. |
| Gibrid R@1 | 48.1% | 53.8% | +5.6 p.p. | 49.0% | 52.1% | +3.1 p.p. |
| Gibrid MRR@10 | 0.658 | 0.696 | +0.037 | 0.665 | 0.690 | +0.025 |
| BM25 yolgʻiz R@5 | 31.2% | 42.5% | +11.2 p.p. | 36.8% | 43.6% | +6.8 p.p. |
| BM25 yolgʻiz R@1 | 20.0% | 23.8% | +3.7 p.p. | 15.4% | 18.3% | +2.9 p.p. |
| BM25 yolgʻiz MRR@10 | 0.299 | 0.350 | +0.052 | 0.283 | 0.335 | +0.052 |
| Dense R@5 | 76.9% | 76.9% | 0 | 78.8% | 78.8% | 0 |
| Dense R@1 | 51.2% | 51.2% | 0 | 50.2% | 50.2% | 0 |
| Dense MRR@10 | 0.678 | 0.678 | 0 | 0.675 | 0.676 | +0.001 |
| Gibrid + boʻlish R@5 | 77.5% | 76.9% | -0.6 p.p. | 77.8% | 79.0% | +1.2 p.p. |
| Gibrid + boʻlish R@1 | 49.4% | 54.4% | +5.0 p.p. | 48.1% | 50.0% | +1.9 p.p. |
| Gibrid + boʻlish MRR@10 | 0.671 | 0.702 | +0.031 | 0.644 | 0.657 | +0.012 |
| Gibrid R@5, lotin | 76.4% | 73.6% | -2.7 p.p. | 75.9% | 76.2% | +0.3 p.p. |
| BM25 R@5, lotin | 34.5% | 49.1% | +14.5 p.p. | 39.6% | 48.2% | +8.6 p.p. |
| Gibrid R@5, kirill | 76.7% | 83.3% | +6.7 p.p. | 85.6% | 85.6% | 0 |
| BM25 R@5, kirill | 30.0% | 46.7% | +16.7 p.p. | 51.1% | 55.6% | +4.4 p.p. |
| Gibrid R@5, rus | 85.0% | 85.0% | 0 | 90.0% | 90.0% | 0 |
| Rad etish (TEST): toʻgʻri / xato | 2/5 · 0/80 | 2/5 · 0/80 | | | | |
| Rad etish (DEV): toʻgʻri / xato | 2/4 · 0/81 | 2/4 · 0/81 | | | | |

## "Bazada yoʻq" savollarni rad etish

Chegara NO_ANSWER_COS = 0.48 (LLM'ga beriladigan 8 ta manbaning eng yuqori cosine'i shundan past boʻlsa — "topilmadi").

| Rejim | qism | toʻgʻri rad etildi | notoʻgʻri rad etildi (javobi bor savol) | aniqlik |
|---|---|---|---|---|
| Dense (bge-m3) | TEST | 2/5 | 0/80 | 96.5% |
| Dense (bge-m3) | DEV | 2/4 | 0/81 | 97.7% |
| Gibrid (RRF) | TEST | 2/5 | 0/80 | 96.5% |
| Gibrid (RRF) | DEV | 2/4 | 0/81 | 97.7% |
| Gibrid + bo'lish | TEST | 2/5 | 0/80 | 96.5% |
| Gibrid + bo'lish | DEV | 2/4 | 0/81 | 97.7% |

## Til / yozuv boʻyicha recall@5 (TEST | DEV)

| Til / yozuv | n (T/D) | Dense (bge-m3) | BM25 | Gibrid (RRF) | Gibrid + bo'lish |
|---|---|---|---|---|---|
| lotin | 55/56 | 75.4% \| 75.0% | 49.1% \| 48.2% | 73.6% \| 76.2% | 73.6% \| 75.3% |
| kirill | 15/15 | 76.7% \| 85.6% | 46.7% \| 55.6% | 83.3% \| 85.6% | 83.3% \| 85.6% |
| rus | 10/10 | 85.0% \| 90.0% | 0.0% \| 0.0% | 85.0% \| 90.0% | 85.0% \| 90.0% |

## Kategoriya boʻyicha recall@5 (TEST | DEV)

| Kategoriya | n (T/D) | Dense (bge-m3) | BM25 | Gibrid (RRF) | Gibrid + bo'lish |
|---|---|---|---|---|---|
| mehnat | 12/12 | 79.2% \| 75.0% | 45.8% \| 45.8% | 83.3% \| 72.2% | 83.3% \| 72.2% |
| jinoyat | 7/6 | 85.7% \| 33.3% | 57.1% \| 16.7% | 85.7% \| 33.3% | 85.7% \| 33.3% |
| fuqarolik | 6/6 | 50.0% \| 66.7% | 58.3% \| 50.0% | 58.3% \| 66.7% | 58.3% \| 66.7% |
| konstitutsiya | 5/5 | 100.0% \| 86.7% | 40.0% \| 66.7% | 100.0% \| 86.7% | 100.0% \| 86.7% |
| oila | 5/6 | 80.0% \| 91.7% | 0.0% \| 50.0% | 80.0% \| 91.7% | 80.0% \| 91.7% |
| soliq | 5/4 | 50.0% \| 100.0% | 0.0% \| 75.0% | 50.0% \| 100.0% | 50.0% \| 100.0% |
| ijtimoiy | 5/4 | 90.0% \| 100.0% | 60.0% \| 75.0% | 90.0% \| 100.0% | 90.0% \| 100.0% |
| saylov | 4/3 | 100.0% \| 50.0% | 50.0% \| 50.0% | 100.0% \| 66.7% | 100.0% \| 66.7% |
| taʼlim | 4/1 | 87.5% \| 100.0% | 0.0% \| 0.0% | 87.5% \| 100.0% | 87.5% \| 50.0% |
| maʼmuriy | 3/5 | 50.0% \| 100.0% | 83.3% \| 60.0% | 50.0% \| 100.0% | 50.0% \| 100.0% |
| uy-joy | 3/1 | 100.0% \| 100.0% | 33.3% \| 100.0% | 100.0% \| 100.0% | 100.0% \| 100.0% |
| isteʼmolchi | 3/1 | 66.7% \| 100.0% | 33.3% \| 0.0% | 66.7% \| 100.0% | 66.7% \| 100.0% |
| bank | 3/1 | 100.0% \| 100.0% | 33.3% \| 100.0% | 66.7% \| 100.0% | 66.7% \| 100.0% |
| tadbirkorlik | 3/4 | 66.7% \| 75.0% | 33.3% \| 12.5% | 66.7% \| 87.5% | 66.7% \| 87.5% |
| sogʻliq | 2/3 | 25.0% \| 83.3% | 75.0% \| 33.3% | 25.0% \| 83.3% | 25.0% \| 100.0% |
| transport | 2/4 | 100.0% \| 100.0% | 100.0% \| 0.0% | 100.0% \| 100.0% | 100.0% \| 100.0% |
| boshqa | 2/1 | 50.0% \| 100.0% | 100.0% \| 100.0% | 50.0% \| 100.0% | 50.0% \| 100.0% |
| yer | 1/2 | 50.0% \| 50.0% | 0.0% \| 50.0% | 50.0% \| 50.0% | 50.0% \| 50.0% |
| intellektual mulk | 1/2 | 100.0% \| 100.0% | 100.0% \| 100.0% | 100.0% \| 100.0% | 100.0% \| 100.0% |
| bojxona | 1/3 | 0.0% \| 66.7% | 0.0% \| 0.0% | 0.0% \| 66.7% | 0.0% \| 66.7% |
| migratsiya | 1/2 | 100.0% \| 50.0% | 0.0% \| 0.0% | 100.0% \| 50.0% | 100.0% \| 50.0% |
| harbiy | 1/2 | 100.0% \| 75.0% | 100.0% \| 0.0% | 100.0% \| 75.0% | 100.0% \| 50.0% |
| axborot | 1/2 | 100.0% \| 75.0% | 0.0% \| 75.0% | 100.0% \| 75.0% | 100.0% \| 75.0% |
| notariat | 0/1 | — \| 100.0% | — \| 0.0% | — \| 100.0% | — \| 100.0% |

## Qiyinlik boʻyicha recall@5 (TEST | DEV)

| Qiyinlik | n (T/D) | Dense (bge-m3) | BM25 | Gibrid (RRF) | Gibrid + bo'lish |
|---|---|---|---|---|---|
| o'rta | 35/32 | 67.1% \| 82.8% | 37.1% \| 31.2% | 67.1% \| 84.4% | 67.1% \| 84.4% |
| oson | 29/25 | 89.7% \| 90.0% | 56.9% \| 66.0% | 89.7% \| 92.0% | 89.7% \| 92.0% |
| qiyin | 16/24 | 75.0% \| 61.8% | 28.1% \| 36.8% | 75.0% \| 60.4% | 75.0% \| 58.3% |

## Sweep: W_BM25 (gibrid) — tanlash DEV boʻyicha

| W_BM25 | DEV R@1 | DEV R@5 | DEV MRR@10 | TEST R@5 | TEST MRR@10 |
|---|---|---|---|---|---|
| 0.0 | 50.2% | 78.8% | 0.676 | 76.9% | 0.678 |
| 0.05 (joriy) | 52.1% | 79.6% | 0.690 | 76.9% | 0.696 |
| 0.1 | 51.6% | 78.0% | 0.678 | 75.6% | 0.684 |
| 0.2 | 51.0% | 76.8% | 0.668 | 75.6% | 0.666 |
| 0.3 | 51.0% | 73.9% | 0.662 | 73.1% | 0.665 |
| 0.4 | 52.3% | 74.5% | 0.671 | 73.1% | 0.653 |
| 0.6 | 52.3% | 76.1% | 0.663 | 70.6% | 0.641 |
| 0.8 | 49.8% | 76.1% | 0.645 | 68.8% | 0.648 |
| 1.0 | 49.2% | 73.0% | 0.632 | 68.1% | 0.649 |
| 1.5 | 47.9% | 66.9% | 0.600 | 65.0% | 0.621 |
| 2.0 | 47.9% | 66.3% | 0.594 | 64.4% | 0.613 |

Eng yaxshi (DEV, recall@5, teng boʻlsa MRR@10): W_BM25 = 0.05. Ruscha savollarda BM25 ishlatilmaydi (RU_BM25 = off: baza oʻzbekcha).

## Sweep: NO_ANSWER_COS (tanlash DEV boʻyicha: xato rad ≤ 1% sharti bilan eng koʻp toʻgʻri rad)

| chegara | DEV toʻgʻri rad | DEV xato rad | TEST toʻgʻri rad | TEST xato rad |
|---|---|---|---|---|
| 0.30 | 0/4 | 0/81 | 0/5 | 0/80 |
| 0.34 | 0/4 | 0/81 | 0/5 | 0/80 |
| 0.38 | 0/4 | 0/81 | 1/5 | 0/80 |
| 0.42 | 0/4 | 0/81 | 1/5 | 0/80 |
| 0.46 | 2/4 | 0/81 | 2/5 | 0/80 |
| 0.48 (joriy) | 2/4 | 0/81 | 2/5 | 0/80 |
| 0.50 | 2/4 | 0/81 | 2/5 | 0/80 |
| 0.54 | 2/4 | 1/81 | 2/5 | 0/80 |
| 0.58 | 2/4 | 11/81 | 2/5 | 9/80 |
| 0.62 | 4/4 | 26/81 | 3/5 | 28/80 |
| 0.66 | 4/4 | 55/81 | 4/5 | 50/80 |
| 0.70 | 4/4 | 69/81 | 5/5 | 67/80 |

Eng yaxshi (DEV): 0.48. 
TEST: javobi bor savollarda eng yaqin cosine min 0.5483, 10-persentil 0.6, mediana 0.6393500000000001; bazada yoʻq savollarda 0.3779, 0.4439, 0.6102, 0.6252, 0.6898. Ikki guruh toʻliq ajralmaydi.
DEV: javobi bor savollarda eng yaqin cosine min 0.5381, 10-persentil 0.6, mediana 0.6478; bazada yoʻq savollarda 0.4315, 0.4481, 0.5805, 0.6101. Ikki guruh toʻliq ajralmaydi.

## Xatolar — TEST (gibrid: gold modda top-5 da yoʻq)

| id | til | savol | gold | gibrid oʻrni | dense oʻrni | BM25 oʻrni |
|---|---|---|---|---|---|---|
| q17 | lotin | Odam necha yoshdan boshlab o'z nomidan har qanday bitim tuza oladi? | Fuqarolik kodeksi (1-qism) 22-m. | >10 | 16 | >40 |
| q18 | lotin | Qarzni undirish uchun sudga murojaat qilishning umumiy muddati necha yil? | Fuqarolik kodeksi (1-qism) 150-m. | 7 | 5 | >40 |
| c07 | kirill | Кўчада бақириб сўкинган одамга қандай маъмурий жазо берилади? | Maʼmuriy javobgarlik toʻgʻrisidagi kodeks 183-m. | >10 | >40 | 1 |
| r06 | rus | Какая ставка налога на добавленную стоимость в Узбекистане? | Soliq kodeksi 258-m. | >10 | 40 | >40 |
| a26 | lotin | 15 yoshli o'g'lim ota-onasining ruxsatisiz o'zi davolanishga rozilik bera oladimi yoki undan bosh tortishi mumkinmi? | Fuqarolar sogʻligʻini saqlash toʻgʻrisida 19-m.; Fuqarolar sogʻligʻini saqlash toʻgʻrisida 26-m. | >10 | >40 | 1 |
| b03 | lotin | Ogay otam meni oz farzandi qilib rasmiylashtirmoqchi, men 12 yoshdaman. Mendan ham rozilik sorashlari shartmi? | Oila kodeksi 155-m. | >10 | 17 | >40 |
| b21 | lotin | Mebel do'koniga divan uchun oldindan to'liq pul to'ladim, lekin kelishilgan kunda olib kelishmadi, ikki haftadan beri paysalga solishyapti. Kechikkan har bir kun uchun menga qancha jarima to'lashlari kerak? | Isteʼmolchilarning huquqlarini himoya qilish toʻgʻrisida 12¹-m. | >10 | >40 | >40 |
| b22 | lotin | Agar bankning litsenziyasi olib qo'yilib, u yopilsa, omonatimdagi pulning qanchasi kafolatlangan holda qaytariladi? | Banklardagi omonatlarni himoya qilish kafolatlari toʻgʻrisida 26-m. | 6 | 3 | >40 |
| c108 | lotin | Sud hukmiga rozi bo'lmasam, apellyatsiya shikoyatini necha kun ichida berishim kerak? | Jinoyat-protsessual kodeksi 497⁴-m. | >10 | 17 | 3 |
| c120 | lotin | Qozog'istonlik qarindoshim o'z mashinasida mehmonga keldi. Uning mashinasi O'zbekistonda bir yilda jami necha kungacha tura oladi? | Bojxona kodeksi 159-m. | 9 | 9 | >40 |
| d12 | lotin | Kvartiramni ikki yil oldin sotib olganman. Hozir sotsam, olgan pulimdan daromad soligʻi toʻlashim kerakmi? | Soliq kodeksi 378-m. | 8 | 10 | 13 |
| d21 | lotin | Kafemga yong'in xavfsizligi bo'yicha tekshiruv kelmoqchi. Bunday tekshiruv necha kungacha cho'zilishi mumkin? | Tadbirkorlik faoliyati erkinligining kafolatlari toʻgʻrisida 39-m. | >10 | >40 | 9 |
| d27 | lotin | Maishiy chiqindini olib ketish xizmati uchun to'lov qilish fuqarolarning majburiyatimi? | Chiqindilar toʻgʻrisida 13-m. | >10 | >40 | 1 |

## Xatolar — DEV (gibrid: gold modda top-5 da yoʻq)

| id | til | savol | gold | gibrid oʻrni | dense oʻrni | BM25 oʻrni |
|---|---|---|---|---|---|---|
| q01 | lotin | Ishchiga har yili kamida necha kun dam olish taʼtili berilishi kerak? | Mehnat kodeksi 217-m. | 9 | 9 | 11 |
| q06 | lotin | 17 yoshli o'smir ishlasa, unga yillik dam olish necha kun beriladi? | Mehnat kodeksi 418-m. | >10 | 22 | 32 |
| c06 | kirill | Бировнинг нарсасини яширинча олиб қўйгани учун қандай жазо бор? | Jinoyat kodeksi 169-m. | 7 | 7 | >40 |
| a10 | lotin | Ikki oy oldin ishga kech qolganimni rahbar o'shanda ko'rgan edi, endi esa shu uchun menga hayfsan bermoqchi. Shuncha vaqt o'tgach jazo berishga haqqi bormi? | Mehnat kodeksi 314-m. | >10 | >40 | >40 |
| b08 | lotin | Ukam vafot etdi, uylanmagan, farzandi yoq edi. Otamiz bir paytlar ota-onalik huquqidan mahrum qilingan, keyin tiklanmagan. Otam ukamdan qolgan mol-mulkka merosxor bola oladimi? | Fuqarolik kodeksi (2-qism) 1119-m. | >10 | >40 | 3 |
| b09 | lotin | Jiyanimga kvartira sovg'a qilgan edim, u esa meni do'pposlab, sog'lig'imga zarar yetkazdi. Sovg'amni qaytarib olishim mumkinmi? | Fuqarolik kodeksi (2-qism) 507-m. | >10 | >40 | >40 |
| b17 | rus | Сосед самовольно занял часть моего участка и поставил там забор, говорит, что потратился на благоустройство. Вернут ли мне землю и должен ли я компенсировать ему расходы? | Yer kodeksi 91-m. | >10 | 20 | >40 |
| c102 | lotin | Ko'chada bir yigit hammaning ko`z oldida qo'limdagi telefonni yulib olib qochdi. Bunday o`g`rilik uchun qanaqa jazo bor? | Jinoyat kodeksi 166-m. | >10 | >40 | >40 |
| c104 | lotin | Do'stim ilgari ichib mashina haydagani uchun bir marta jarimaga tortilgan edi, endi yana mast holda rulda ushlandi. Bu safar unga nima bo'ladi, qamalib ketishi mumkinmi? | Jinoyat kodeksi 261¹-m. | 7 | 7 | >40 |
| c106 | lotin | Akamga qarshi jinoyat ishi ochildi, tergovchi meni guvoh sifatida chaqiryapti. Akam haqida ko'rsatma berishdan bosh tortishga haqqim bormi? | Jinoyat-protsessual kodeksi 116-m.; Jinoyat-protsessual kodeksi 66-m.; Konstitutsiya 28-m. | >10 | 29 | 8 |
| c122 | lotin | Oilam bilan boshqa davlatga butunlay ko'chib ketyapmiz. Uy-ro'zg'or buyumlarimizni olib chiqsak, bojxonaga pul to'lashimiz kerakmi? | Bojxona kodeksi 157-m. | >10 | 23 | >40 |
| c126 | lotin | O'zbekiston fuqarosiman, boshqa shaharda kvartira ijaraga oldim. U yerda vaqtincha ro'yxatga necha muddatga qo'yishadi va muddat tugab, yana yashashda davom etsam nima qilishim kerak? | Yashash joyi va turgan joyi boʻyicha roʻyxatdan oʻtkazish toʻgʻrisida 13-m. | >10 | 21 | 35 |
| d06 | lotin | Siyosiy partiya parlamentdan o'rin olishi uchun saylovda kamida necha foiz ovoz to'plashi kerak? | Saylov kodeksi 96-m.; Saylov kodeksi 96¹-m. | 9 | 10 | 1 |
