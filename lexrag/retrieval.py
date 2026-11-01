"""Gibrid qidiruv: dense (bge-m3 + ChromaDB) + leksik (BM25), Reciprocal Rank Fusion bilan.

Nega gibrid: dense qidiruv ma'noni yaxshi ushlaydi, lekin yaqin yozilishdagi so'zlarni chalkashtiradi
("oʻgʻirlik" va "odam oʻgʻirlash"). BM25 aniq atamalarni (modda nomi, "oʻgʻrilik", "taʼtil") ushlaydi.
Ikkala ro'yxat RRF bilan birlashtiriladi: score = sum(1 / (60 + rank)).

O'zbek tili qo'shimchali til ("taʼtil", "taʼtilni", "taʼtilining"): BM25 tokenlari lexrag/stem.py dagi qoidaga
asoslangan o'zak ajratuvchi bilan olinadi (avval so'z 7 harfgacha kesilardi). Tokenizator sozlamasi indeks bilan
birga saqlanadi (ids.json "tokenizer"); so'rov ham aynan shu sozlama bilan tokenlanadi, shuning uchun eski indeks
(7 harf) ham yangi kod bilan to'g'ri ishlaydi.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import config
from . import stem as uzstem
from .indexer import embed_query, get_collection
from .normalize import normalize_text
from .translit import cyr_to_lat, repair_latin

log = logging.getLogger(__name__)

MODEL = "BAAI/bge-m3"
# LEXRAG_BM25_DIR: boshqa indeks bilan ishlash (yangi indeksni ishlab turgan serverga tegmasdan sinash uchun)
BM25_DIR = Path(os.environ.get("LEXRAG_BM25_DIR") or config.INDEX_DIR / "bm25")
WORD = re.compile(r"[a-zʻʼ0-9¹²³⁴⁵⁶⁷⁸⁹⁰]+")
STEM = 7                  # eski tokenizator ("trunc7"): so'zning birinchi 7 harfi
# yangi indeks tokenizatori (stem.tokenize): deriv - so'z yasovchi qo'shimchalar ham olinadimi, trunc - o'zakni kesish
INDEX_TOKENIZER = {"kind": "stem", "deriv": False, "trunc": None}
# Quyidagi standartlar eval/ DEV qismida tanlangan (scripts/tune_stage4.py -> eval/tuning_stage4.json):
# so'rovdagi stopwordlar (faqat "stem" indeksida): none | basic | legal. Indeksda stopword olib tashlanmaydi -
# shuning uchun ro'yxatni indeksni qayta qurmasdan sozlash mumkin. DEV: BM25 R@5 none 0.405, basic 0.436,
# legal 0.436 ("modda", "qonun" ni tashlash ta'sir qilmadi)
QUERY_STOP = "basic"
# kirill / apostrofsiz savolni korpus lug'ati bo'yicha tiklash (translit.repair_latin): "bm25" - faqat BM25 so'rovi
# tiklanadi (dense asl lotinlashtirilgan matnni oladi), "all" - dense ham, "off" - tiklanmaydi.
# DEV: "all" kirill dense R@5 ni 0.856 -> 0.789 ga tushirdi (d08), "bm25" - dense o'zgarmaydi, kirill BM25 0.511 -> 0.578
REPAIR = "bm25"
# kirill savol uchun dense: "lat" - lotinga o'girilgan matn, "both" - lotin + asl kirill, RRF bilan.
# DEV: "both" kirill gibrid R@5 0.856 -> 0.722 (bge-m3 asl kirillda yomonroq topadi)
CYR_DENSE = "lat"
# ruscha savol uchun BM25: "off" - BM25 ishlatilmaydi (baza o'zbekcha), "glossary" - faqat lug'atdagi o'zbekcha
# atamalar, "glossary+translit" - atamalar + lotinga o'girilgan ruscha matn (3-bosqichdagi usul).
# DEV: gibrid R@5 uchalasida 0.796, MRR off 0.689 >= glossary 0.688 = glossary+translit 0.688
RU_BM25 = "off"
RRF_K = 60
# Og'irliklar eval/ to'plamida sozlangan (python -m lexrag eval, eval/sweep.json). W_BM25 0.6 edi: BM25 parafrazali
# savollarda umumiy so'zlar ("uchun", "qanday", "kerak") bo'yicha shovqin beradi va RRF'da dense topgan moddani
# pastga suradi (W_BM25=0.6 da gibrid recall@5 61% < dense 82%). 0.05 da BM25 faqat dense'ning yaqin o'rinlarini
# qayta tartiblaydi:
# gibrid recall@5 61.2% -> 83.7%, MRR@10 0.509 -> 0.716 (eval/README.md). W_BM25=0 (sof dense) MRR'da biroz
# yaxshiroq (0.733), lekin recall@5 pastroq (81.5%).
# 4-bosqich (170 savol, stemmer bilan, DEV sweep): eng yaxshisi yana 0.05 (R@5 0.796, MRR 0.688); stemmer bilan
# katta og'irlik kamroq zarar qiladi (W=0.6: R@5 0.677 -> 0.749), lekin optimum siljimadi.
W_DENSE, W_BM25 = 1.0, 0.05
# ruscha savol: BM25 og'irligi W_BM25 ga nisbatan (lug'atdan o'zbekcha atama topilsa / topilmasa)
RU_W = (0.75, 0.25)


TRUNC7 = {"kind": "trunc7"}


def tokenize_with(text: str, cfg: dict, stop: str = "none") -> list[str]:
    if cfg.get("kind") != "stem":
        t = normalize_text(text).lower()
        return [w[:STEM] for w in WORD.findall(t) if len(w) > 1 or w.isdigit()]
    return uzstem.tokenize(text, stop=stop, deriv=bool(cfg.get("deriv")), trunc=cfg.get("trunc"))


def tokenize(text: str) -> list[str]:
    """So'rov tokenlari: yuklangan BM25 indeksining tokenizatori + QUERY_STOP."""
    return tokenize_with(text, _bm25_cfg(), QUERY_STOP)


def prepare_query(q: str, repair: bool | None = None) -> str:
    """Kirillcha savolni lotinga o'giradi va normallashtiradi. repair (standart: REPAIR == "all"): korpusda yo'q
    so'zlar lug'at bo'yicha tiklanadi - kirillda rus klaviaturasi (у/к/х/г o'rniga ў/қ/ҳ/ғ) va apostrofsiz lotin."""
    q = q.strip()
    cyr = bool(re.search(r"[А-Яа-яЎўҚқҒғҲҳЁё]", q))
    if cyr:
        q = cyr_to_lat(q)
    q = normalize_text(q)
    if (REPAIR == "all") if repair is None else repair:
        voc = vocab()
        if voc:
            q = repair_latin(q, voc, letters=cyr)
    return q


# ---------------------------------------------------------------- BM25
def build_bm25(out_dir: Path | None = None, cfg: dict | None = None) -> Path:
    """BM25 indeksini quradi. out_dir (standart BM25_DIR) - ishlab turgan server indeksiga tegmaslik uchun boshqa
    papkaga qurib, keyin almashtirish mumkin (python -m lexrag bm25 --out data/index/bm25_new)."""
    import bm25s
    out_dir = Path(out_dir or BM25_DIR)
    cfg = dict(cfg or INDEX_TOKENIZER)
    ids, metas, corpus = [], [], []
    words: Counter = Counter()
    with open(config.CHUNKS, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            ids.append(c["chunk_id"])
            metas.append({"status": c.get("status"), "amend": bool(c.get("is_amending_law"))})
            corpus.append(tokenize_with(c["text"], cfg))
            words.update(WORD.findall(normalize_text(c["text"]).lower()))
    retr = bm25s.BM25()
    retr.index(corpus, show_progress=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    retr.save(str(out_dir))
    (out_dir / "ids.json").write_text(json.dumps({"ids": ids, "metas": metas, "tokenizer": cfg}), encoding="utf-8")
    (out_dir / "vocab.json").write_text(json.dumps(build_vocab(words), ensure_ascii=False), encoding="utf-8")
    log.info("BM25 indeks: %d chunk, %s -> %s", len(ids), cfg, out_dir)
    return out_dir


def build_vocab(words: Counter, min_count: int = 2) -> dict:
    """Korpus lug'ati so'z tiklash uchun: {skelet: [eng ko'p uchragan shakl, skelet soni, shakl soni]}.
    Skelet - kichik harf, apostroflarsiz ("oʻgʻirlik" -> "ogirlik")."""
    best: dict = {}
    for w, n in words.items():
        if n < min_count or len(w) < 2:
            continue
        sk = uzstem.fold(w)
        b = best.get(sk)
        if b is None:
            best[sk] = [w, n, n]
        else:
            b[1] += n
            if n > b[2]:
                b[0], b[2] = w, n
    return best


@lru_cache(maxsize=1)
def _bm25():
    import bm25s
    if not (BM25_DIR / "ids.json").exists() or \
            (BM25_DIR / "ids.json").stat().st_mtime < config.CHUNKS.stat().st_mtime:
        build_bm25()
    retr = bm25s.BM25.load(str(BM25_DIR))
    d = json.loads((BM25_DIR / "ids.json").read_text(encoding="utf-8"))
    # tokenizer yo'q - 4-bosqichdan oldingi indeks (7 harf)
    return retr, d["ids"], d["metas"], d.get("tokenizer") or TRUNC7


def _bm25_cfg() -> dict:
    return _bm25()[3]


@lru_cache(maxsize=1)
def vocab() -> dict:
    p = BM25_DIR / "vocab.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def use_bm25_dir(path: Path) -> None:
    """Boshqa BM25 indeksiga o'tish (baholash / sozlash uchun): keshlar tozalanadi."""
    global BM25_DIR
    BM25_DIR = Path(path)
    _bm25.cache_clear()
    if hasattr(vocab, "cache_clear"):
        vocab.cache_clear()


@lru_cache(maxsize=1)
def _doc_types() -> dict[str, str]:
    """doc_id -> doc_type (Qonun / Kodeks / Konstitutsiya), metadata.csv dan. chunk_id = <doc_id>_..."""
    import csv
    with open(config.METADATA_CSV, encoding="utf-8-sig") as f:
        return {r["id"]: r["doc_type"] for r in csv.DictReader(f)}


def bm25_search(query: str, n: int, only_active: bool, no_amending: bool,
                doc_types: list[str] | None = None, scores_out: dict | None = None) -> list[str]:
    """scores_out berilsa (X-ray, baholash) - {chunk_id: BM25 ball} bilan to'ldiriladi."""
    retr, ids, metas, _ = _bm25()
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
    (kodeks, konstitutsiya, pensiya kabi umumiy so'zlar) beriladi va og'irligi kamaytiriladi (RU_W).
    RU_BM25: "glossary" - faqat lug'at atamalari (atama topilmasa BM25 ishlatilmaydi), "off" - BM25 yo'q,
    "glossary+translit" - 3-bosqichdagi usul (lotinlashtirilgan ruscha so'zlar BM25'da shovqin beradi)."""
    base = W_BM25 if w_bm25 is None else w_bm25
    if lang == "ru":
        from .lang import ru_bm25_terms
        terms = ru_bm25_terms(query)
        if RU_BM25 == "off" or (RU_BM25 == "glossary" and not terms):
            return normalize_text(query), "", 0.0
        q_bm = terms if RU_BM25 == "glossary" else f"{terms} {prepare_query(query, repair=False)}".strip()
        return normalize_text(query), q_bm, base * (RU_W[0] if terms else RU_W[1])
    q = prepare_query(query)
    q_bm = prepare_query(query, repair=True) if REPAIR == "bm25" else q
    return q, q_bm, base


def candidates(query: str, lang: str | None, n_each: int, only_active: bool = True, no_amending: bool = True,
               doc_types: list[str] | None = None, mode: str = "hybrid", timing: dict | None = None,
               bm_scores: dict | None = None) -> dict:
    """Ikkala usulning nomzodlari (RRF dan oldin). hybrid_search va baholash (evaluate._raw) shuni chaqiradi.
    -> {dense: [id], cos: {id: cosine}, lex: [id], w_bm25, w_factor, q_dense, q_bm25, q_dense_alt}

    Kirill savol (CYR_DENSE="both"): dense ikki marta - lotinga o'girilgan va asl kirill matn bilan, ro'yxatlar RRF
    bilan birlashadi, cosine - ikkalasining kattasi."""
    q_dense, q_bm25, w_bm25 = query_texts(query, lang)
    factor = query_texts(query, lang, 1.0)[2]
    alt = query.strip() if (CYR_DENSE == "both" and lang == "uz_cyr" and re.search(r"[А-Яа-яЎўҚқҒғҲҳ]", query)) else None
    dense, cos = [], {}
    if mode in ("hybrid", "dense"):
        dense, cos = dense_search(q_dense, n_each, only_active, no_amending, doc_types, timing=timing)
        if alt:
            d2, c2 = dense_search(alt, n_each, only_active, no_amending, doc_types)
            f = rrf([(dense, 1.0), (d2, 1.0)])
            dense = sorted(f, key=f.get, reverse=True)[:n_each]
            cos = {c: max(cos.get(c) or 0, c2.get(c) or 0) for c in dense}
    t_bm = time.perf_counter()
    lex = bm25_search(q_bm25, n_each, only_active, no_amending, doc_types, scores_out=bm_scores) \
        if mode in ("hybrid", "bm25") and q_bm25 else []
    if timing is not None:
        timing["_t_bm25"], timing["bm25"] = t_bm, _ms(time.perf_counter() - t_bm)
    return {"dense": dense, "cos": cos, "lex": lex, "w_bm25": w_bm25, "w_factor": factor,
            "q_dense": q_dense, "q_bm25": q_bm25, "q_dense_alt": alt}


TRACE_TOP = 10  # X-ray: har usulning nechta eng yaxshi natijasi ko'rsatiladi


def hybrid_search(query: str, k: int = 8, only_active: bool = True, no_amending: bool = True,
                  n_each: int = 40, mode: str = "hybrid", doc_types: list[str] | None = None,
                  lang: str | None = None, trace: dict | None = None) -> list[dict]:
    """mode: hybrid | dense | bm25. doc_types: faqat shu turdagi hujjatlar (None - hammasi).
    lang="ru": ruscha savol (query_texts). Natija: [{chunk_id, score, rank_dense, rank_bm25, text, ...meta}]

    trace (X-ray): dict berilsa, qidiruv ichi yoziladi - so'rov matnlari, og'irliklar, dense va BM25 ro'yxatlari
    (ball bilan), RRF natijasi va har bosqich vaqti. trace=None bo'lsa ortiqcha hech narsa hisoblanmaydi."""
    t0 = time.perf_counter()
    tm: dict | None = {} if trace is not None else None
    bm_scores: dict | None = {} if trace is not None else None
    c = candidates(query, lang, n_each, only_active, no_amending, doc_types, mode, timing=tm, bm_scores=bm_scores)
    dense, cos, lex, w_bm25 = c["dense"], c["cos"], c["lex"], c["w_bm25"]
    q_dense, q_bm25 = c["q_dense"], c["q_bm25"]
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
        if tm and "_t_embed" in tm:
            spans += [{"key": "embed", "start": tm["_t_embed"], "ms": tm["embed"]},
                      {"key": "dense", "start": tm["_t_dense"], "ms": tm["dense"]}]
        if mode in ("hybrid", "bm25") and tm and "_t_bm25" in tm:
            spans.append({"key": "bm25", "start": tm["_t_bm25"], "ms": tm["bm25"]})
        spans += [{"key": "rrf", "start": t_rrf, "ms": _ms(t_fetch - t_rrf)},
                  {"key": "fetch", "start": t_fetch, "ms": _ms(t_end - t_fetch)}]
        trace.update({
            "query": query, "q_dense": q_dense, "q_bm25": q_bm25, "bm25_tokens": tokenize(q_bm25)[:40],
            "q_dense_alt": c["q_dense_alt"], "mode": mode, "lang": lang,
            "params": {"w_dense": W_DENSE, "w_bm25": w_bm25, "w_bm25_default": W_BM25, "rrf_k": RRF_K,
                       "n_each": n_each, "k": k, "query_stop": QUERY_STOP, "ru_bm25": RU_BM25,
                       "tokenizer": _bm25_cfg()},
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
