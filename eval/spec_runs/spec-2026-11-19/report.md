# Spetsifikatsiya run: spec-2026-11-19

Javoblar: 100/100; javobi bor 90, javobsiz 10; system variantlari: 1

| Metrika | Natija | Maqsad |
|---|---|---|
| hit@5_doc_% | 91.1 | >= 90 |
| hit@5_article_% | 84.4 | >= 80 |
| mrr | 0.699 | >= 0.70 |
| context_precision_%_proxy_doc | 63.6 | >= 60 |
| citation_accuracy_%_proxy_gold_article_cited | 93.8 | >= 90 |
| fabricated_citations | 0 | 0 |
| outdated_norm_citations | 0 | 0 |
| no_answer_accuracy | 10/10 | >= 9/10 |
| false_reject_on_answerable | 9 |  |
| latency_ms_p50 | 5340 | <= 5000 |
| latency_ms_p95 | 27427 | <= 12000 |
| error_or_timeout_% | 0.0 | <= 2 |
| answer_correctness | hisoblanmadi (expected_answer + LLM-hakam yoki qoʻlda) |  |
| faithfulness | hisoblanmadi (LLM-hakam kerak) |  |

Kategoriyalar: {"bir_nechta_modda": {"n": 20, "hit@5_article_%": 90.0, "mrr": 0.747}, "faktik": {"n": 14, "hit@5_article_%": 92.9, "mrr": 0.651}, "javobsiz": {"n": 10, "no_answer_ok": 10}, "raqamlar": {"n": 33, "hit@5_article_%": 72.7, "mrr": 0.657}, "rus_kirill": {"n": 23, "hit@5_article_%": 91.3, "mrr": 0.748}}

Xato sababi (retrieval / manba / no_answer / xato): {"retrieval": ["q008", "q010", "q020", "q025", "q027", "q032", "q033", "q043", "q044", "q046", "q059", "q066", "q070", "q086"], "manba": [], "no_answer": [], "xato": []}
