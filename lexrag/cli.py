"""Buyruqlar: python -m lexrag <buyruq> [opsiyalar]

  list                    - "Qonunlar" ro'yxatini yig'ish (checkpoint bilan)
  fetch [--limit N]       - hujjat HTML + kartochkasini yuklash (raw/)
  parse [--limit N]       - raw -> data/clean/<id>.json + data/metadata.csv
  chunk                   - clean -> data/chunks.jsonl
  report                  - report.md (statistika va tekshiruv)
  verify [--n 4]          - tasodifiy hujjatlarni saytdagi jonli matn bilan solishtirish
  all [--limit N]         - list + fetch + parse + chunk + report
  index [--model ...]     - chunklarni vektorlashtirib ChromaDB ga yozish
  search "savol" [-k 5]   - gibrid qidiruv (bge-m3 + BM25), manbalar bilan
  ask "savol"             - RAG: LLM manbali javob yozadi (.env da API kalit kerak)
  export-colab            - chunklarni Colab GPU uchun eksport (data/colab/embed_input.jsonl.gz)
  import-vectors [fayl]   - Colab'dan kelgan vectors.npz ni tekshirib ChromaDB ga yozish
  eval [--modes ...] [--k 10] [--no-sweep]
                          - qidiruv sifatini baholash (eval/questions.jsonl, LLM'siz) -> eval/results.*
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config


def _rows(limit: int | None, ids: list[str] | None = None):
    from .scraper import load_list_index, select_sample
    rows = load_list_index()
    if not rows:
        sys.exit("Avval `python -m lexrag list` ishga tushiring.")
    if ids:
        s = set(ids)
        return [r for r in rows if r["lex_id"] in s]
    sample_file = config.STATE / "sample_ids.json"
    if limit:
        sample = select_sample(rows, limit)
        sample_file.write_text(json.dumps([r["lex_id"] for r in sample]), encoding="utf-8")
        return sample
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lexrag", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["list", "fetch", "parse", "chunk", "report", "verify",
                                    "all", "index", "search", "ask", "export-colab", "import-vectors", "eval"])
    ap.add_argument("query", nargs="?")
    ap.add_argument("--limit", type=int, help="faqat N ta hujjat (ro'yxat bo'ylab teng taqsimlangan namuna)")
    ap.add_argument("--ids", nargs="*", help="aniq lex_id lar")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("-k", "--k", type=int, default=None, help="search: 5, ask: 8, eval: 10")
    ap.add_argument("--modes", default=None, help="eval: dense,bm25,hybrid,hybrid_plan (standart: hammasi)")
    ap.add_argument("--no-sweep", action="store_true", help="eval: W_BM25 va NO_ANSWER_COS sweep'siz")
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--merge-short", action="store_true",
                    help="bir bob ichidagi qisqa moddalarni ~300 tokengacha birlashtirish")
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "bm25"], help="search rejimi")
    ap.add_argument("--all-status", action="store_true",
                    help="search: kuchini yo'qotgan hujjatlar ham (standart: faqat amaldagilar)")
    ap.add_argument("--include-amending", action="store_true",
                    help="search: o'zgartirish kirituvchi qonunlarni ham (standart: chiqarib tashlanadi)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if a.cmd in ("list", "all"):
        from .scraper import scrape_list
        rows = scrape_list()
        print(f"Ro'yxatda {len(rows)} ta hujjat (saytda ko'rsatilgan: {config.EXPECTED_TOTAL})")
    if a.cmd in ("fetch", "all"):
        from .scraper import fetch_docs
        print(fetch_docs(_rows(a.limit, a.ids)))
    if a.cmd in ("parse", "all"):
        from .parser import parse_all
        print(parse_all(_rows(a.limit, a.ids)))
    if a.cmd in ("chunk", "all"):
        from .chunker import chunk_all
        print(chunk_all(merge_short=a.merge_short))
    if a.cmd in ("report", "all"):
        from .report import build_report
        build_report()
        print(f"Hisobot: {config.REPORT}")
    if a.cmd == "verify":
        from .verify import verify_random
        verify_random(a.n)
    if a.cmd == "index":
        from .indexer import build_index
        build_index(model_name=a.model, batch_size=a.batch_size)
    if a.cmd == "export-colab":
        from .colab import export_input
        export_input()
    if a.cmd == "import-vectors":
        from .colab import import_vectors
        import_vectors(a.query or str(config.DATA / "colab" / "vectors.npz"))
    if a.cmd == "ask":
        from .rag import cli_ask
        cli_ask(a.query or input("Savol: "), k=a.k or 8)
    if a.cmd == "search":
        from .search import main as search_main
        search_main(a.query, k=a.k or 5, model_name=a.model, only_active=not a.all_status, no_amending=not a.include_amending,
                    mode=a.mode)
    if a.cmd == "eval":
        from .evaluate import cli as eval_cli
        eval_cli(a.modes, k=a.k or 10, do_sweep=not a.no_sweep)


if __name__ == "__main__":
    main()
