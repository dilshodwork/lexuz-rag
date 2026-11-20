"""Query rewrite tajribasi: python scripts/rewrite_exp.py dev|test [gate]. Qayta yozish LLM chaqiruvi, data/state keshida."""
import json, sys, logging, time
sys.path.insert(0, ".")
logging.disable(logging.WARNING)
from lexrag import rewrite
from lexrag.lang import resolve_lang
from lexrag.retrieval import hybrid_search, rrf

split = sys.argv[1]
gate = float(sys.argv[2]) if len(sys.argv) > 2 else rewrite.REWRITE_GATE
gate_rows = {r["id"]: r for r in json.load(open(sys.argv[3] if len(sys.argv) > 3 else
                                                 "eval/rewrite_gate.json"))}
qs = [json.loads(l) for l in open("eval/questions.jsonl", encoding="utf-8")]
qs = [q for q in qs if q["split"] == split and q.get("gold")]


def rank_of(hits, gold, k=5):
    for i, h in enumerate(hits[:k], 1):
        if (str(h.get("doc_id")), str(h.get("article_number"))) in gold:
            return i
    return None


W = [0.5, 0.7, 1.0, 1.5]
res = {"orig": [], "rw_only": [], **{f"fuse{w}": [] for w in W}}
calls = 0
changed = []
for q in qs:
    gold = {(g["doc_id"], g["article"]) for g in q["gold"]}
    lang = resolve_lang(q["question"], None)
    orig = hybrid_search(q["question"], k=20, lang=lang)
    r0 = rank_of(orig, gold)
    res["orig"].append(r0)
    if gate_rows[q["id"]]["best"] >= gate:
        for key in res:
            if key != "orig":
                res[key].append(r0)
        continue
    had = rewrite.cached(q["question"])
    rq = rewrite.rewrite(q["question"])
    calls += not had
    if not rq:
        for key in res:
            if key != "orig":
                res[key].append(r0)
        continue
    rw = hybrid_search(rq, k=20, lang="uz")
    res["rw_only"].append(rank_of(rw, gold))
    by = {h["chunk_id"]: h for h in orig + rw}
    for w in W:
        f = rrf([([h["chunk_id"] for h in orig], 1.0), ([h["chunk_id"] for h in rw], w)])
        top = [by[c] for c in sorted(f, key=f.get, reverse=True)]
        rk = rank_of(top, gold)
        res[f"fuse{w}"].append(rk)
        if w == 1.0 and rk != r0:
            changed.append((q["id"], r0, rk, q["question"][:60], rq[:90]))
n = len(qs)
print(f"{split}: n={n} gate<{gate} new LLM calls={calls}")
for key, ranks in res.items():
    print(f"  {key:9s} hit@5={sum(1 for r in ranks if r)/n:.3f} mrr@5={sum(1/r for r in ranks if r)/n:.3f}")
for c in changed:
    print("  ", c)
