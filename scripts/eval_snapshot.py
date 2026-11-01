"""Baholashni ishga tushirib natijani alohida faylga saqlash (eval/results.json ga tegmaydi).

    .venv/bin/python scripts/eval_snapshot.py eval/baseline_v2.json      # joriy kod bilan "oldin" surati

Fayl results.json bilan bir xil tuzilishda, sweep ichida ("sweep" kaliti). Terminalga dev/test qisqa jadvali.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag import evaluate as E  # noqa: E402


def show(r: dict) -> None:
    for s, B in r["by_split"].items():
        print(f"{s}: {B['n_questions']} savol ({B['n_answerable']} javobli, {B['n_none']} yoʻq)")
        for m in r["meta"]["modes"]:
            x = B["summary"][m]
            print(f"  {m:12} R@1 {x['recall@1']:.3f}  R@5 {x['recall@5']:.3f}  R@10 {x['recall@10']:.3f}  MRR {x['mrr@10']:.3f}")
        rj = B["rejection"].get("hybrid")
        if rj:
            print(f"  rad etish: {rj['correct_reject']}/{rj['n_none']} toʻgʻri, {rj['false_reject']}/{rj['n_answerable']} xato")
        for m in ("dense", "bm25", "hybrid"):
            print(f"  til R@5 {m:7}", {k: round(v[m]["recall@5"], 3) for k, v in B["slices"]["lang"].items()})


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--bm25-dir", default=None, help="BM25 indeksi (masalan data/index/bm25_new)")
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    if a.bm25_dir:
        from lexrag import retrieval
        retrieval.use_bm25_dir(ROOT / a.bm25_dir)
    out = Path(a.out)
    res = E.run(write=False)
    r = res["results"]
    r["sweep"] = res["sweep"]
    out.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    show(r)
    sw = res["sweep"]
    if sw:
        print("sweep (dev): eng yaxshi W_BM25", sw["w_bm25"]["best"]["w_bm25"], "| NO_ANSWER_COS", sw["no_answer_cos"]["best"]["threshold"])
    print("vaqt", r["meta"]["elapsed_s"], "s ->", out)


if __name__ == "__main__":
    main()
