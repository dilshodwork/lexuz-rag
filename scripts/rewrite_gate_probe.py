"""Retrieval-only (LLMsiz): asl savolning eng yaqin cosine i va gold modda o rni -> eval/rewrite_gate.json. Ishlatish: python scripts/rewrite_gate_probe.py eval/rewrite_gate.json"""
import json, sys, logging
sys.path.insert(0, ".")
logging.disable(logging.WARNING)
from lexrag import rag
from lexrag.retrieval import chunk_meta

qs = [json.loads(l) for l in open("eval/questions.jsonl", encoding="utf-8")]
out = []
for q in qs:
    p = rag.prepare(q["question"], k=5, only_active=True, no_amending=True)
    cards = p["sources"]
    metas = chunk_meta([c["chunk_id"] for c in cards])
    gold = {(g["doc_id"], g["article"]) for g in q.get("gold") or []}
    rank = None
    for c in cards:
        m = metas.get(c["chunk_id"], {})
        if (str(m.get("doc_id")), str(c.get("article_number"))) in gold:
            rank = c["n"]; break
    out.append({"id": q["id"], "split": q["split"], "lang": q["lang"], "answerable": bool(gold),
                "best": p.get("best_cosine") or max((c.get("cosine") or 0) for c in cards) if cards else 0,
                "rank": rank, "no_answer": p["no_answer"], "parts": len(p.get("parts") or [])})
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False)
for sp in ("dev", "test"):
    rows = [r for r in out if r["split"] == sp and r["answerable"]]
    hit = sum(1 for r in rows if r["rank"]); mrr = sum(1 / r["rank"] for r in rows if r["rank"]) / len(rows)
    print(sp, len(rows), "hit@5", round(hit / len(rows), 3), "mrr@5", round(mrr, 3))
    for g in (0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 1.0):
        below = [r for r in rows if r["best"] < g]
        print(f"  gate<{g}: {len(below)} q, of them miss {sum(1 for r in below if not r['rank'])} "
              f"(all misses {len(rows) - hit})")
