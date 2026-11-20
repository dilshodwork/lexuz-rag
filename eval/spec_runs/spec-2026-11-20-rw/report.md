# Spetsifikatsiya run: spec-2026-11-20-rw

Javoblar: 100/100; javobi bor 90, javobsiz 10; system variantlari: 4

| Metrika | Natija | Maqsad |
|---|---|---|
| hit@5_doc_% | 98.9 | >= 90 |
| hit@5_article_% | 93.3 | >= 80 |
| mrr | 0.781 | >= 0.70 |
| context_precision_%_proxy_doc | 72.2 | >= 60 |
| citation_accuracy_%_proxy_gold_article_cited | 96.6 | >= 90 |
| fabricated_citations | 0 | 0 |
| outdated_norm_citations | 0 | 0 |
| no_answer_accuracy | 10/10 | >= 9/10 |
| false_reject_on_answerable | 3 |  |
| latency_ms_p50 | 4477 | <= 5000 |
| latency_ms_p95 | 17540 | <= 12000 |
| error_or_timeout_% | 0.0 | <= 2 |
| answer_correctness | hisoblanmadi (expected_answer + LLM-hakam yoki qoʻlda) |  |
| faithfulness | hisoblanmadi (LLM-hakam kerak) |  |

Kategoriyalar: {"bir_nechta_modda": {"n": 20, "hit@5_article_%": 95.0, "mrr": 0.842}, "faktik": {"n": 14, "hit@5_article_%": 92.9, "mrr": 0.792}, "javobsiz": {"n": 10, "no_answer_ok": 10}, "raqamlar": {"n": 33, "hit@5_article_%": 90.9, "mrr": 0.745}, "rus_kirill": {"n": 23, "hit@5_article_%": 95.7, "mrr": 0.773}}

Xato sababi (retrieval / manba / no_answer / xato): {"retrieval": ["q020", "q027", "q032", "q059", "q070", "q086"], "manba": [], "no_answer": [], "xato": []}
