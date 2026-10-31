"""Oddiy semantik qidiruv: savol -> eng mos k ta chunk, manbasi bilan.

    python -m lexrag search "Mikromoliya tashkiloti bank bo'lishi mumkinmi?" -k 5
    python -m lexrag.search "..." --all-status  # eski (kuchini yo'qotgan) hujjatlar ham
Standart holatda faqat amaldagi hujjatlar qidiriladi: aks holda eski Mehnat kodeksi (1995) kabi
kuchini yo'qotgan matnlar yangisidan yuqori chiqib qolishi mumkin.
    python -m lexrag.search "..." --include-amending   # o'zgartirish kirituvchi qonunlar ham

O'zgartirish kirituvchi qonunlar ("... so'zlar bilan almashtirilsin") standart holatda qidiruvga
kirmaydi: ularning yangi tahriri asosiy qonun matnida allaqachon bor, ular esa natijani
ko'rsatma matnlari bilan to'ldirib yuboradi.
"""
from __future__ import annotations

import argparse
import textwrap



def search(query: str, k: int = 5, model_name: str = "BAAI/bge-m3", only_active: bool = True,
           no_amending: bool = True, mode: str = "hybrid"):
    # gibrid: bge-m3 (ma'no) + BM25 (so'z), RRF bilan; kirillcha savol lotinga o'giriladi
    from .retrieval import hybrid_search
    return hybrid_search(query, k=k, only_active=only_active, no_amending=no_amending, mode=mode)


def print_hits(query: str, hits: list[dict]):
    print(f"\nSavol: {query}\n")
    for i, h in enumerate(hits, 1):
        body = h["text"].split("\n\n", 1)[-1]
        print(f"[{i}] rrf={h['score']:.4f} cos={h.get('cosine')} (dense #{h.get('rank_dense')}, bm25 #{h.get('rank_bm25')})"
              f" | {h.get('status', '')} | oxirgi tahrir: {h.get('last_edition_date', '')}")
        print(f"    {h.get('heading', '')}")
        print(f"    Manba: {h.get('source_url', '')}")
        print(textwrap.indent(textwrap.shorten(body, 420, placeholder=" ..."), "    "))
        print()


def main(query: str | None = None, k: int = 5, model_name: str = "BAAI/bge-m3", only_active: bool = True,
         no_amending: bool = True, mode: str = "hybrid"):
    if not query:
        query = input("Savol: ").strip()
    print_hits(query, search(query, k=k, model_name=model_name, only_active=only_active,
                             no_amending=no_amending, mode=mode))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--all-status", action="store_true",
                    help="kuchini yo'qotgan va amalda bo'lmagan hujjatlar ham (standart: faqat amaldagilar)")
    ap.add_argument("--include-amending", action="store_true",
                    help="o'zgartirish kirituvchi qonunlarni ham qidirish (standart: chiqarib tashlanadi)")
    a = ap.parse_args()
    main(a.query, a.k, a.model, not a.all_status, not a.include_amending)
