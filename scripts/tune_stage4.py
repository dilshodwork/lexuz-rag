"""4-bosqich sozlash: faqat DEV savollarida variantlarni solishtirish (test'ga qaralmaydi).

    .venv/bin/python scripts/tune_stage4.py [--build] [--only cyr,bm25,ru,w]

Variantlar retrieval modulidagi sozlamalar orqali (REPAIR, CYR_DENSE, RU_BM25, QUERY_STOP, BM25 indeksi) beriladi;
baholash evaluate.eval_question orqali - ilovadagi kod bilan aynan bir xil. Dense natijalari (so'rov matni bo'yicha)
keshlanadi: BM25 variantlari dense'ni qayta hisoblamaydi.

BM25 indekslari:
  old        data/index/bm25            (3-bosqich, 7 harf; o'zgartirilmaydi)
  stem       data/index/bm25_new        (stem.py, so'z yasovchilar olinmaydi) - ishlab chiqarish uchun nomzod
  stem_deriv /tmp/dalil_bm25/stem_deriv (stem.py + -lik/-chi/-siz/-li)
Natija: eval/tuning_stage4.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag import config, retrieval as R  # noqa: E402
from lexrag import evaluate as E  # noqa: E402

IDX = {"old": config.INDEX_DIR / "bm25", "stem": config.INDEX_DIR / "bm25_new",
       "stem_deriv": Path("/tmp/dalil_bm25/stem_deriv")}
CFG = {"stem": {"kind": "stem", "deriv": False, "trunc": None},
       "stem_deriv": {"kind": "stem", "deriv": True, "trunc": None}}
OUT = ROOT / "eval" / "tuning_stage4.json"

_dense_cache: dict = {}
_orig_dense = R.dense_search


def cached_dense(query, n, only_active, no_amending, doc_types=None, timing=None):
    key = (query, n, only_active, no_amending, tuple(doc_types or ()))
    if key not in _dense_cache:
        _dense_cache[key] = _orig_dense(query, n, only_active, no_amending, doc_types)
    if timing is not None:
        timing.update(embed=0.0, dense=0.0)
    return _dense_cache[key]


R.dense_search = cached_dense
E.dense_search = cached_dense

_VOCAB = None


def _vocab():
    return _VOCAB


def set_cfg(index="old", repair="off", cyr_dense="lat", ru_bm25="glossary+translit", stop="basic", w=0.05):
    global _VOCAB
    if R.BM25_DIR != IDX[index]:
        R.use_bm25_dir(IDX[index])
    if _VOCAB is None:
        _VOCAB = json.loads((IDX["stem"] / "vocab.json").read_text(encoding="utf-8"))
    R.vocab = _vocab                  # lug'at har doim yangi indeksdagi (eski indeksda vocab.json yo'q)
    R.REPAIR, R.CYR_DENSE, R.RU_BM25, R.QUERY_STOP, R.W_BM25 = repair, cyr_dense, ru_bm25, stop, w


def run_dev(qs, label, **cfg):
    set_cfg(**cfg)
    per_q, raws = [], []
    for q in qs:
        r, raw = E.eval_question(q, ("dense", "bm25", "hybrid"), 10)
        per_q.append(r)
        raws.append(raw)
    out = {"label": label, "cfg": cfg, "summary": {}, "lang": {}}
    for m in ("dense", "bm25", "hybrid"):
        s = E.summarize(per_q, m)
        out["summary"][m] = {k: s[k] for k in ("recall@1", "recall@5", "recall@10", "mrr@10")}
    for lang, row in E._slices(per_q, ("dense", "bm25", "hybrid"), "lang").items():
        out["lang"][lang] = {m: {"n": v["n"], "recall@5": v["recall@5"], "mrr@10": v["mrr@10"]} for m, v in row.items()}
    out["w_grid"] = E._w_grid(per_q, raws, 10)
    out["per_q"] = {r["id"]: {"dense": r["modes"]["dense"].get("metrics", {}).get("rank"),
                              "bm25": r["modes"]["bm25"].get("metrics", {}).get("rank"),
                              "hybrid": r["modes"]["hybrid"].get("metrics", {}).get("rank")} for r in per_q if r["answerable"]}
    s = out["summary"]
    lg = out["lang"]
    print(f"{label:42} dense R@5 {s['dense']['recall@5']:.3f} MRR {s['dense']['mrr@10']:.3f} | "
          f"bm25 R@5 {s['bm25']['recall@5']:.3f} MRR {s['bm25']['mrr@10']:.3f} | "
          f"hyb R@5 {s['hybrid']['recall@5']:.3f} MRR {s['hybrid']['mrr@10']:.3f} | "
          + " ".join(f"{k}:{v['hybrid']['recall@5']:.3f}/{v['dense']['recall@5']:.3f}/{v['bm25']['recall@5']:.3f}"
                     for k, v in lg.items()), flush=True)
    return out


REPAIR_SEL, STOP_SEL = "bm25", "basic"     # DEV natijasidan keyin tanlangan qiymatlar (eval/README.md)


def diff(qs, runs):
    """Kirill va apostrofsiz lotin savollar: variantlar orasida o'zgargan gold o'rinlari (dense/BM25/gibrid)."""
    for q in qs:
        if not q["answerable"]:
            continue
        lat_noapo = q["lang"] == "uz" and not any(c in q["question"] for c in "'ʻʼ`’")
        if q["lang"] != "uz_cyr" and not lat_noapo:
            continue
        rows = [r["per_q"].get(q["id"]) for r in runs]
        if len({json.dumps(x) for x in rows}) > 1:
            print(f"  {q['id']:5} {q['lang']:6} " + " | ".join(f"{x['dense']}/{x['bm25']}/{x['hybrid']}" for x in rows),
                  flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="BM25 indekslarini (stem, stem_deriv) qurish")
    ap.add_argument("--only", default="cyr,bm25,ru,w")
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    for name, cfg in CFG.items():
        if a.build or not (IDX[name] / "ids.json").exists():
            t0 = time.time()
            R.build_bm25(IDX[name], cfg)
            print(f"qurildi {name}: {time.time() - t0:.0f} s -> {IDX[name]}", flush=True)
    qs = [q for q in E.load_questions() if q["split"] == "dev"]
    print(f"DEV: {len(qs)} savol ({sum(q['answerable'] for q in qs)} javobli)", flush=True)
    only = set(a.only.split(","))
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    res["meta"] = {"split": "dev", "n": len(qs), "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    base = dict(index="old", repair="off", cyr_dense="lat", ru_bm25="glossary+translit", stop="basic", w=0.05)
    if "cyr" in only:          # 2-qadam: kirill
        res["cyr"] = [run_dev(qs, "3-bosqich (oldin)", **base),
                      run_dev(qs, "+ soʻz tiklash: dense+BM25", **{**base, "repair": "all"}),
                      run_dev(qs, "+ soʻz tiklash: faqat BM25", **{**base, "repair": "bm25"}),
                      run_dev(qs, "+ tiklash(BM25) + dense lotin+kirill", **{**base, "repair": "bm25", "cyr_dense": "both"}),
                      run_dev(qs, "dense lotin+kirill (tiklashsiz)", **{**base, "cyr_dense": "both"})]
        diff(qs, res["cyr"])
    if "bm25" in only:         # 3-qadam: tokenizator va stopwordlar
        b2 = {**base, "repair": REPAIR_SEL}
        res["bm25"] = [run_dev(qs, "BM25 eski (7 harf)", **b2)]
        for idx in ("stem", "stem_deriv"):
            for stop in ("none", "basic", "legal"):
                res["bm25"].append(run_dev(qs, f"BM25 {idx}, stop={stop}", **{**b2, "index": idx, "stop": stop}))
    if "ru" in only:           # ruscha savol uchun BM25
        b3 = {**base, "repair": REPAIR_SEL, "index": "stem", "stop": STOP_SEL}
        res["ru"] = [run_dev(qs, f"ru BM25 = {m}", **{**b3, "ru_bm25": m}) for m in ("glossary+translit", "glossary", "off")]
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", OUT)


if __name__ == "__main__":
    main()
