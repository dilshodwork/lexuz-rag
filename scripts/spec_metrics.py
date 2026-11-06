"""Ustoz spetsifikatsiyasi metrikalari ("RAG API — test spetsifikatsiyasi", 6-bo'lim) bizning to'plamda.

report.md dagi R@k - Recall@k: savolning BARCHA gold moddalaridan qanchasi top-k da (17 TEST savolda 2-3 gold).
Spetsifikatsiya esa Hit@k ni o'lchaydi: kamida bitta kutilgan modda top-k da. Bu skript ilovadagi qidiruvning
o'zini (retrieval.hybrid_search, faqat amaldagi hujjatlar) chaqiradi va yozadi eval/spec_metrics.json:
    Hit@1/3/5/10 (modda), Hit@5 (hujjat), MRR@10 - DEV va TEST alohida; sozlash yo'q, faqat o'lchov.

    .venv/bin/python scripts/spec_metrics.py                 # ~1 daqiqa
    .venv/bin/python scripts/spec_metrics.py --rerank        # + reranker tajribasi (DEV, top-15, ~4 daqiqa)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag.lang import detect_lang  # noqa: E402
from lexrag.retrieval import hybrid_search, prepare_query  # noqa: E402

OUT = ROOT / "eval" / "spec_metrics.json"
RERANK_MODEL = "jinaai/jina-reranker-v2-base-multilingual"
RERANK_N, RERANK_CHARS = 15, 700


def first(hits: list[dict], gold: set, doc_level: bool = False) -> int | None:
    docs = {d for d, _ in gold}
    for i, h in enumerate(hits, 1):
        d = str(h.get("doc_id") or h["chunk_id"].split("_")[0])
        if (d in docs) if doc_level else ((d, str(h.get("article_number") or "")) in gold):
            return i
    return None


def summary(rows: list[dict], mode: str = "full") -> dict:
    n = len(rows)
    hit = lambda k: round(sum(1 for r in rows if r["rank"] and r["rank"] <= k) / n, 4)  # noqa: E731
    out = {"n": n, **{f"hit@{k}": hit(k) for k in (1, 3, 5, 10)},
           "mrr@10": round(sum(1 / r["rank"] for r in rows if r["rank"] and r["rank"] <= 10) / n, 4)}
    if mode == "full":
        out["doc_hit@5"] = round(sum(1 for r in rows if r["doc_rank"] and r["doc_rank"] <= 5) / n, 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerank", action="store_true")
    a = ap.parse_args()
    qs = [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").open(encoding="utf-8")]
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    res: dict = {"method": "retrieval.hybrid_search (ilovadagi qidiruv), faqat amaldagi hujjatlar; Hit@k - kamida bitta "
                           "gold modda top-k da; doc_hit@5 - gold hujjat top-5 da", "splits": {}}
    enc = None
    if a.rerank:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        enc = TextCrossEncoder(RERANK_MODEL)
    for split in ("dev", "test"):
        rows, rr_rows, rr_ms = [], [], []
        for q in qs:
            if q.get("split") != split or not q.get("gold"):
                continue
            gold = {(g["doc_id"], g["article"]) for g in q["gold"]}
            lang = detect_lang(q["question"])
            hits = hybrid_search(q["question"], k=RERANK_N if enc else 10, lang=lang)
            rows.append({"id": q["id"], "lang": q.get("lang"), "rank": first(hits[:10], gold),
                         "doc_rank": first(hits[:10], gold, True)})
            if enc and split == "dev":  # reranker faqat DEV'da (TEST'ga qarab qaror qilinmaydi)
                query = q["question"] if lang == "ru" else prepare_query(q["question"])
                t0 = time.perf_counter()
                sc = list(enc.rerank(query, [h["text"][:RERANK_CHARS] for h in hits]))
                rr_ms.append((time.perf_counter() - t0) * 1000)
                order = [h for _, h in sorted(zip(sc, hits), key=lambda x: -x[0])]
                rr_rows.append({"rank": first(order, gold), "base": rows[-1]["rank"], "lang": q.get("lang")})
        res["splits"][split] = {"summary": summary(rows), "by_lang": {
            lg: summary([r for r in rows if r["lang"] == lg]) for lg in ("uz", "uz_cyr", "ru")
            if any(r["lang"] == lg for r in rows)}}
        if rr_rows:
            def rs(key: str, lg: str | None = None) -> dict:
                return summary([{"rank": r[key]} for r in rr_rows if lg is None or r["lang"] == lg], "rank_only")
            res["rerank"] = {"model": RERANK_MODEL, "split": "dev", "top_n": RERANK_N, "chars": RERANK_CHARS,
                             "base": rs("base"), "reranked": rs("rank"),
                             "ms_per_question": round(sum(rr_ms) / len(rr_ms)),
                             "by_lang_hit5": {lg: [rs("base", lg)["hit@5"], rs("rank", lg)["hit@5"]]
                                              for lg in ("uz", "uz_cyr", "ru") if any(r["lang"] == lg for r in rr_rows)}}
    if "rerank" not in res and "rerank" in old:
        res["rerank"] = old["rerank"]
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for split, d in res["splits"].items():
        s = d["summary"]
        print(f"{split}: n={s['n']} Hit@1 {s['hit@1']:.1%} Hit@5 {s['hit@5']:.1%} Hit@10 {s['hit@10']:.1%} "
              f"MRR {s['mrr@10']:.3f} | hujjat Hit@5 {s['doc_hit@5']:.1%}")
    if "rerank" in res:
        r = res["rerank"]
        print(f"rerank (DEV): Hit@5 {r['base']['hit@5']:.1%} -> {r['reranked']['hit@5']:.1%}, MRR {r['base']['mrr@10']:.3f} -> "
              f"{r['reranked']['mrr@10']:.3f}, +{r['ms_per_question']} ms/savol")
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
