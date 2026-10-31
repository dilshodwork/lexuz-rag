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
# Og'irliklar eval/ to'plamida sozlangan (python -m lexrag eval, eval/sweep.json). W_BM25 0.6 edi: BM25 parafrazali
# savollarda umumiy so'zlar ("uchun", "qanday", "kerak") bo'yicha shovqin beradi va RRF'da dense topgan moddani
# pastga suradi (W_BM25=0.6 da gibrid recall@5 61% < dense 82%). 0.05 da BM25 faqat dense'ning yaqin o'rinlarini
# qayta tartiblaydi:
# gibrid recall@5 61.2% -> 83.7%, MRR@10 0.509 -> 0.716 (eval/README.md). W_BM25=0 (sof dense) MRR'da biroz
# yaxshiroq (0.733), lekin recall@5 pastroq (81.5%).
W_DENSE, W_BM25 = 1.0, 0.05
# ruscha savol: BM25 og'irligi W_BM25 ga nisbatan (lug'atdan o'zbekcha atama topilsa / topilmasa)
RU_W = (0.75, 0.25)


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


@lru_cache(maxsize=1)
def _doc_types() -> dict[str, str]:
    """doc_id -> doc_type (Qonun / Kodeks / Konstitutsiya), metadata.csv dan. chunk_id = <doc_id>_..."""
    import csv
    with open(config.METADATA_CSV, encoding="utf-8-sig") as f:
        return {r["id"]: r["doc_type"] for r in csv.DictReader(f)}


def bm25_search(query: str, n: int, only_active: bool, no_amending: bool,
                doc_types: list[str] | None = None, scores_out: dict | None = None) -> list[str]:
    """scores_out berilsa (X-ray, baholash) - {chunk_id: BM25 ball} bilan to'ldiriladi."""
    retr, ids, metas = _bm25()
    toks = tokenize(query)
    if not toks:
        return []
    scores = retr.get_scores(toks)
    order = np.argsort(-scores)
    types = _doc_types() if doc_types else None
    out = []
    for i in order[: n * 20]:
        if scores[i] <= 0:
            break
        m = metas[i]
        if only_active and m["status"] != "amalda":
            continue
        if no_amending and m["amend"]:
            continue
        if types is not None and types.get(ids[i].split("_", 1)[0]) not in doc_types:
            continue
        out.append(ids[i])
        if scores_out is not None:
            scores_out[ids[i]] = round(float(scores[i]), 3)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- dense
def _where(only_active: bool, no_amending: bool, doc_types: list[str] | None = None):
    conds = []
    if only_active:
        conds.append({"status": "amalda"})
    if no_amending:
        conds.append({"is_amending_law": False})
    if doc_types:
        conds.append({"doc_type": {"$in": list(doc_types)}})
    return None if not conds else conds[0] if len(conds) == 1 else {"$and": conds}


def dense_search(query: str, n: int, only_active: bool, no_amending: bool,
                 doc_types: list[str] | None = None, timing: dict | None = None) -> tuple[list[str], dict]:
    """(id lar, {id: cosine}). timing berilsa - {"embed": ms, "dense": ms} (savol embeddingi va ChromaDB alohida)."""
    col = get_collection(MODEL, create=False)
    t0 = time.perf_counter()
    emb = embed_query(MODEL, query)
    t1 = time.perf_counter()
    res = col.query(query_embeddings=[emb], n_results=n,
                    where=_where(only_active, no_amending, doc_types), include=["distances"])
    if timing is not None:
        timing.update(embed=_ms(t1 - t0), dense=_ms(time.perf_counter() - t1), _t_embed=t0, _t_dense=t1)
    ids = res["ids"][0]
    return ids, {i: round(1 - d, 4) for i, d in zip(ids, res["distances"][0])}


def _ms(sec: float) -> float:
    return round(sec * 1000, 1)


def rrf(lists: list[tuple[list[str], float]], rrf_k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion: har ro'yxat (id lar, og'irlik) -> {id: sum(w / (rrf_k + rank))}.
    hybrid_search va baholash (lexrag/evaluate.py, sweep) aynan shu funksiyani ishlatadi."""
    fused: dict[str, float] = {}
    for lst, w in lists:
        for r, cid in enumerate(lst):
            fused[cid] = fused.get(cid, 0.0) + w / (rrf_k + r + 1)
    return fused


# ---------------------------------------------------------------- gibrid
def query_texts(query: str, lang: str | None = None, w_bm25: float | None = None) -> tuple[str, str, float]:
    """(dense uchun matn, BM25 uchun matn, BM25 og'irligi). w_bm25 - asosiy og'irlik (standart W_BM25; sweep uchun).

    Ruscha savol: bge-m3 ko'p tilli, shuning uchun dense asl ruscha matn bilan qidiradi. BM25 o'zbekcha
    matnda ruscha so'zlarni topmaydi: unga kichik lug'atdagi o'zbekcha atamalar + lotinlashtirilgan savol
    (kodeks, konstitutsiya, pensiya kabi umumiy so'zlar) beriladi va og'irligi kamaytiriladi (RU_W)."""
    base = W_BM25 if w_bm25 is None else w_bm25
    if lang == "ru":
        from .lang import ru_bm25_terms
        terms = ru_bm25_terms(query)
        return normalize_text(query), f"{terms} {prepare_query(query)}".strip(), base * (RU_W[0] if terms else RU_W[1])
    q = prepare_query(query)
    return q, q, base


TRACE_TOP = 10  # X-ray: har usulning nechta eng yaxshi natijasi ko'rsatiladi


def hybrid_search(query: str, k: int = 8, only_active: bool = True, no_amending: bool = True,
                  n_each: int = 40, mode: str = "hybrid", doc_types: list[str] | None = None,
                  lang: str | None = None, trace: dict | None = None) -> list[dict]:
    """mode: hybrid | dense | bm25. doc_types: faqat shu turdagi hujjatlar (None - hammasi).
    lang="ru": ruscha savol (query_texts). Natija: [{chunk_id, score, rank_dense, rank_bm25, text, ...meta}]

    trace (X-ray): dict berilsa, qidiruv ichi yoziladi - so'rov matnlari, og'irliklar, dense va BM25 ro'yxatlari
    (ball bilan), RRF natijasi va har bosqich vaqti. trace=None bo'lsa ortiqcha hech narsa hisoblanmaydi."""
    q_dense, q_bm25, w_bm25 = query_texts(query, lang)
    t0 = time.perf_counter()
    tm: dict | None = {} if trace is not None else None
    bm_scores: dict | None = {} if trace is not None else None
    dense, cos = dense_search(q_dense, n_each, only_active, no_amending, doc_types, timing=tm) \
        if mode in ("hybrid", "dense") else ([], {})
    t_bm = time.perf_counter()
    lex = bm25_search(q_bm25, n_each, only_active, no_amending, doc_types, scores_out=bm_scores) \
        if mode in ("hybrid", "bm25") else []
    t_rrf = time.perf_counter()
    fused = rrf([(dense, W_DENSE), (lex, w_bm25)])
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    t_fetch = time.perf_counter()
    out = get_chunks(top) if top else []
    for h in out:
        cid = h["chunk_id"]
        h.update({"score": round(fused[cid], 5), "cosine": cos.get(cid),
                  "rank_dense": dense.index(cid) + 1 if cid in dense else None,
                  "rank_bm25": lex.index(cid) + 1 if cid in lex else None})
    t_end = time.perf_counter()
    if trace is not None:
        spans = []
        if tm:
            spans += [{"key": "embed", "start": tm["_t_embed"], "ms": tm["embed"]},
                      {"key": "dense", "start": tm["_t_dense"], "ms": tm["dense"]}]
        if mode in ("hybrid", "bm25"):
            spans.append({"key": "bm25", "start": t_bm, "ms": _ms(t_rrf - t_bm)})
        spans += [{"key": "rrf", "start": t_rrf, "ms": _ms(t_fetch - t_rrf)},
                  {"key": "fetch", "start": t_fetch, "ms": _ms(t_end - t_fetch)}]
        trace.update({
            "query": query, "q_dense": q_dense, "q_bm25": q_bm25, "bm25_tokens": tokenize(q_bm25)[:40],
            "mode": mode, "lang": lang,
            "params": {"w_dense": W_DENSE, "w_bm25": w_bm25, "w_bm25_default": W_BM25, "rrf_k": RRF_K,
                       "n_each": n_each, "k": k},
            "filters": {"only_active": only_active, "no_amending": no_amending, "doc_types": doc_types},
            "counts": {"dense": len(dense), "bm25": len(lex), "fused": len(fused)},
            "dense": [{"chunk_id": c, "rank": i + 1, "cosine": cos.get(c)} for i, c in enumerate(dense[:TRACE_TOP])],
            "bm25": [{"chunk_id": c, "rank": i + 1, "score": bm_scores.get(c)} for i, c in enumerate(lex[:TRACE_TOP])],
            "fused": [{"chunk_id": h["chunk_id"], "rank": i + 1, "score": h["score"], "cosine": h["cosine"],
                       "rank_dense": h["rank_dense"], "rank_bm25": h["rank_bm25"],
                       "via": "both" if h["rank_dense"] and h["rank_bm25"] else "dense" if h["rank_dense"] else "bm25"}
                      for i, h in enumerate(out)],
            "spans": spans, "ms": _ms(t_end - t0),
        })
    log.debug("hybrid_search %.2fs", time.perf_counter() - t0)
    return out


def chunk_meta(ids: list[str]) -> dict[str, dict]:
    """Faqat metadata (matnsiz): {chunk_id: {doc_id, doc_title, article_number, article_title, status, ...}}.
    X-ray yorliqlari va baholash (gold moddani aniqlash) uchun."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    got = get_collection(MODEL, create=False).get(ids=ids, include=["metadatas"])
    return dict(zip(got["ids"], got["metadatas"]))


def get_chunks(ids: list[str], embeddings: bool = False) -> list[dict]:
    """Chunklarni id bo'yicha (berilgan tartibda). Yo'q id'lar tashlab ketiladi."""
    if not ids:
        return []
    col = get_collection(MODEL, create=False)
    got = col.get(ids=list(ids), include=["documents", "metadatas"] + (["embeddings"] if embeddings else []))
    embs = got.get("embeddings") if embeddings else None
    by_id = {i: (got["documents"][j], got["metadatas"][j], None if embs is None else embs[j])
             for j, i in enumerate(got["ids"])}
    out = []
    for cid in ids:
        if cid not in by_id:
            continue
        doc, meta, emb = by_id[cid]
        h = {"chunk_id": cid, "score": None, "cosine": None, "rank_dense": None, "rank_bm25": None, "text": doc, **meta}
        if embeddings:
            h["embedding"] = emb
        out.append(h)
    return out
