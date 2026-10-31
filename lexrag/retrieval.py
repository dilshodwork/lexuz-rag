"""Gibrid qidiruv: dense (bge-m3 + ChromaDB) + leksik (BM25), Reciprocal Rank Fusion bilan.

Nega gibrid: dense qidiruv ma'noni yaxshi ushlaydi, lekin yaqin yozilishdagi so'zlarni chalkashtiradi
("oʻgʻirlik" va "odam oʻgʻirlash"). BM25 aniq atamalarni (modda nomi, "oʻgʻrilik", "taʼtil") ushlaydi.
Ikkala ro'yxat RRF bilan birlashtiriladi: score = sum(1 / (60 + rank)).

O'zbek tili qo'shimchali til ("taʼtil", "taʼtilni", "taʼtilining"), shuning uchun BM25 uchun so'zlar
birinchi 7 harfgacha qisqartiriladi (oddiy "stem").
"""
from __future__ import annotations

import json
import logging
import re
import time
from functools import lru_cache

import numpy as np

from . import config
from .indexer import embed_query, get_collection
from .normalize import normalize_text
from .translit import cyr_to_lat

log = logging.getLogger(__name__)

MODEL = "BAAI/bge-m3"
BM25_DIR = config.INDEX_DIR / "bm25"
WORD = re.compile(r"[a-zʻʼ0-9¹²³⁴⁵⁶⁷⁸⁹⁰]+")
STEM = 7
RRF_K = 60
# dense ko'proq ishonchli (sinovlarda BM25 umumiy so'zlar bo'yicha shovqin beradi); eval bilan sozlanadi
W_DENSE, W_BM25 = 1.0, 0.6


def tokenize(text: str) -> list[str]:
    t = normalize_text(text).lower()
    return [w[:STEM] for w in WORD.findall(t) if len(w) > 1 or w.isdigit()]


def prepare_query(q: str) -> str:
    """Kirillcha savolni lotinga o'giradi va normallashtiradi."""
    q = q.strip()
    if re.search(r"[А-Яа-яЎўҚқҒғҲҳЁё]", q):
        q = cyr_to_lat(q)
    return normalize_text(q)


# ---------------------------------------------------------------- BM25
def build_bm25():
    import bm25s
    ids, metas, corpus = [], [], []
    with open(config.CHUNKS, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            ids.append(c["chunk_id"])
            metas.append({"status": c.get("status"), "amend": bool(c.get("is_amending_law"))})
            corpus.append(tokenize(c["text"]))
    retr = bm25s.BM25()
    retr.index(corpus, show_progress=False)
    BM25_DIR.mkdir(parents=True, exist_ok=True)
    retr.save(str(BM25_DIR))
    (BM25_DIR / "ids.json").write_text(json.dumps({"ids": ids, "metas": metas}), encoding="utf-8")
    log.info("BM25 indeks: %d chunk", len(ids))


@lru_cache(maxsize=1)
def _bm25():
    import bm25s
    if not (BM25_DIR / "ids.json").exists() or \
            (BM25_DIR / "ids.json").stat().st_mtime < config.CHUNKS.stat().st_mtime:
        build_bm25()
    retr = bm25s.BM25.load(str(BM25_DIR))
    d = json.loads((BM25_DIR / "ids.json").read_text(encoding="utf-8"))
    return retr, d["ids"], d["metas"]


def bm25_search(query: str, n: int, only_active: bool, no_amending: bool) -> list[str]:
    retr, ids, metas = _bm25()
    toks = tokenize(query)
    if not toks:
        return []
    scores = retr.get_scores(toks)
    order = np.argsort(-scores)
    out = []
    for i in order[: n * 20]:
        if scores[i] <= 0:
            break
        m = metas[i]
        if only_active and m["status"] != "amalda":
            continue
        if no_amending and m["amend"]:
            continue
        out.append(ids[i])
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- dense
def _where(only_active: bool, no_amending: bool):
    conds = []
    if only_active:
        conds.append({"status": "amalda"})
    if no_amending:
        conds.append({"is_amending_law": False})
    return None if not conds else conds[0] if len(conds) == 1 else {"$and": conds}


def dense_search(query: str, n: int, only_active: bool, no_amending: bool) -> tuple[list[str], dict]:
    """(id lar, {id: cosine})"""
    col = get_collection(MODEL, create=False)
    res = col.query(query_embeddings=[embed_query(MODEL, query)], n_results=n,
                    where=_where(only_active, no_amending), include=["distances"])
    ids = res["ids"][0]
    return ids, {i: round(1 - d, 4) for i, d in zip(ids, res["distances"][0])}


# ---------------------------------------------------------------- gibrid
def hybrid_search(query: str, k: int = 8, only_active: bool = True, no_amending: bool = True,
                  n_each: int = 40, mode: str = "hybrid") -> list[dict]:
    """mode: hybrid | dense | bm25. Natija: [{chunk_id, score, rank_dense, rank_bm25, text, ...meta}]"""
    q = prepare_query(query)
    t0 = time.time()
    dense, cos = dense_search(q, n_each, only_active, no_amending) if mode in ("hybrid", "dense") else ([], {})
    lex = bm25_search(q, n_each, only_active, no_amending) if mode in ("hybrid", "bm25") else []
    fused: dict[str, float] = {}
    for lst, w in ((dense, W_DENSE), (lex, W_BM25)):
        for r, cid in enumerate(lst):
            fused[cid] = fused.get(cid, 0.0) + w / (RRF_K + r + 1)
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    if not top:
        return []
    col = get_collection(MODEL, create=False)
    got = col.get(ids=top, include=["documents", "metadatas"])
    by_id = {i: (d, m) for i, d, m in zip(got["ids"], got["documents"], got["metadatas"])}
    out = []
    for cid in top:
        doc, meta = by_id[cid]
        out.append({"chunk_id": cid, "score": round(fused[cid], 5), "cosine": cos.get(cid),
                    "rank_dense": dense.index(cid) + 1 if cid in dense else None,
                    "rank_bm25": lex.index(cid) + 1 if cid in lex else None,
                    "text": doc, **meta})
    log.debug("hybrid_search %.2fs", time.time() - t0)
    return out
