"""Chunklarni vektorlashtirish va ChromaDB ga yozish.

Embedding fastembed (ONNX Runtime) orqali hisoblanadi - PyTorch shart emas, Intel Mac'da ham ishlaydi.
Standart model: BAAI/bge-m3 (ko'p tilli, 8192 tokengacha, 1024 o'lcham, CLS pooling).
Muqobil: intfloat/multilingual-e5-large (512 token chegarasi bor, "query:/passage:" prefikslari bilan).

Qayta ishga tushirilsa, kolleksiyada bor chunk_id lar o'tkazib yuboriladi (checkpoint).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from functools import lru_cache

from tqdm import tqdm

from . import config

log = logging.getLogger(__name__)

COLLECTION = "lex_qonunlar"
CHROMA_DIR = config.INDEX_DIR / "chroma"

META_KEYS = ["doc_id", "lex_id", "doc_title", "doc_type", "doc_number", "adoption_date", "issuing_body",
             "status", "is_amending_law", "collection", "last_edition_date", "unit_type", "article_number", "article_title", "annex", "section",
             "chapter", "heading", "chunk_index", "n_chunks_in_unit", "source_url", "doc_url", "n_tokens"]


def _is_e5(model_name: str) -> bool:
    return "e5" in model_name.lower()


@lru_cache(maxsize=2)
def get_model(model_name: str):
    from fastembed import TextEmbedding
    if model_name == "BAAI/bge-m3":
        from fastembed.common.model_description import ModelSource, PoolingType
        known = {m["model"] for m in TextEmbedding.list_supported_models()}
        if model_name not in known:
            TextEmbedding.add_custom_model(
                model=model_name, pooling=PoolingType.CLS, normalization=True,
                sources=ModelSource(hf="BAAI/bge-m3"), dim=1024,
                model_file="onnx/model.onnx", additional_files=["onnx/model.onnx_data"],
            )
    return TextEmbedding(model_name=model_name, cache_dir=str(config.ROOT / ".models"))


def embed_passages(model_name: str, texts: list[str], batch_size: int = 1):
    m = get_model(model_name)
    if _is_e5(model_name):
        texts = ["passage: " + t for t in texts]
    return [v.tolist() for v in m.embed(texts, batch_size=batch_size)]


def embed_query(model_name: str, q: str):
    m = get_model(model_name)
    if _is_e5(model_name):
        q = "query: " + q
    return next(iter(m.embed([q]))).tolist()


def get_collection(model_name: str, create: bool = True):
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if create:
        return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine", "model": model_name})
    return client.get_collection(COLLECTION)


def _meta(c: dict) -> dict:
    out = {}
    for k in META_KEYS:
        v = c.get(k)
        if v is None:
            continue
        out[k] = v if isinstance(v, (str, int, float, bool)) else json.dumps(v, ensure_ascii=False)
    if c.get("amendments"):
        out["amendments"] = json.dumps(c["amendments"], ensure_ascii=False)[:4000]
    out["text_hash"] = _hash(c["text"])
    out["meta_hash"] = _hash(json.dumps(out, sort_keys=True, ensure_ascii=False))
    return out


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def build_index(model_name: str = "BAAI/bge-m3", batch_size: int = 1):
    col = get_collection(model_name)
    stored_model = (col.metadata or {}).get("model")
    if stored_model and stored_model != model_name:
        raise SystemExit(f"Kolleksiya {stored_model} bilan qurilgan. Boshqa model uchun {CHROMA_DIR} ni o'chiring.")
    with open(config.CHUNKS, encoding="utf-8") as f:
        chunks = [json.loads(l) for l in f if l.strip()]
    # checkpoint: indeksda bor va matni o'zgarmagan chunklar qayta hisoblanmaydi
    existing: dict[str, tuple] = {}
    total = col.count()
    for off in range(0, total, 5000):
        got = col.get(limit=5000, offset=off, include=["metadatas"])
        for i, m in zip(got["ids"], got["metadatas"]):
            existing[i] = ((m or {}).get("text_hash"), (m or {}).get("meta_hash"))
    wanted = {c["chunk_id"] for c in chunks}
    stale = [i for i in existing if i not in wanted]
    if stale:
        for off in range(0, len(stale), 5000):
            col.delete(ids=stale[off:off + 5000])
        log.info("Eskirgan %d chunk indeksdan o'chirildi", len(stale))
    todo = [c for c in chunks if (existing.get(c["chunk_id"]) or (None,))[0] != _hash(c["text"])]
    # matni o'zgarmagan, faqat metadata'si o'zgargan chunklar - embeddingsiz yangilanadi
    todo_ids = {c["chunk_id"] for c in todo}
    meta_only = [c for c in chunks if c["chunk_id"] not in todo_ids and c["chunk_id"] in existing
                 and existing[c["chunk_id"]][1] != _meta(c)["meta_hash"]]
    for off in range(0, len(meta_only), 1000):
        b = meta_only[off:off + 1000]
        col.update(ids=[c["chunk_id"] for c in b], metadatas=[_meta(c) for c in b])
    if meta_only:
        log.info("Faqat metadata yangilandi: %d chunk", len(meta_only))
    log.info("Chunklar: %d, indeksda tayyor: %d, hisoblanadi: %d", len(chunks), len(chunks) - len(todo), len(todo))
    t0 = time.time()
    step = 32  # shuncha chunkdan keyin bazaga yoziladi (checkpoint)
    todo.sort(key=lambda c: c["n_tokens"])  # o'xshash uzunliklar bir batchda - padding kam
    for i in tqdm(range(0, len(todo), step), desc="embedding"):
        batch = todo[i:i + step]
        vecs = embed_passages(model_name, [c["text"] for c in batch], batch_size=batch_size)
        col.upsert(ids=[c["chunk_id"] for c in batch], embeddings=vecs,
                   documents=[c["text"] for c in batch], metadatas=[_meta(c) for c in batch])
    log.info("Tayyor: %d chunk, %.0fs; kolleksiyada %d", len(todo), time.time() - t0, col.count())
    return col.count()
