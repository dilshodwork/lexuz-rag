"""Embeddingni Google Colab GPU'da hisoblash uchun eksport/import.

Model, og'irliklar va sozlamalar bir xil (BAAI/bge-m3, CLS pooling, L2 normalizatsiya, fp32):
faqat hisoblash qurilmasi boshqa. Import paytida tasodifiy chunklar shu Mac'da ONNX bilan qayta
hisoblanadi va Colab vektorlari bilan cosine o'xshashlik solishtiriladi (>= 0.999 bo'lishi kerak).

    python -m lexrag export-colab                 # -> data/colab/embed_input.jsonl.gz
    (Colab: colab/embed_bge_m3.ipynb)             # -> vectors.npz
    python -m lexrag import-vectors data/colab/vectors.npz
"""
from __future__ import annotations

import gzip
import json
import logging
import random

import numpy as np
from tqdm import tqdm

from . import config
from .indexer import _hash, _meta, embed_passages, get_collection

log = logging.getLogger(__name__)

COLAB_DIR = config.DATA / "colab"
MODEL = "BAAI/bge-m3"


def _load_chunks() -> list[dict]:
    with open(config.CHUNKS, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def export_input() -> str:
    COLAB_DIR.mkdir(parents=True, exist_ok=True)
    out = COLAB_DIR / "embed_input.jsonl.gz"
    chunks = _load_chunks()
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps({"id": c["chunk_id"], "h": _hash(c["text"]), "text": c["text"]},
                               ensure_ascii=False) + "\n")
    mb = out.stat().st_size / 1e6
    print(f"{len(chunks)} chunk -> {out} ({mb:.0f} MB)")
    return str(out)


def import_vectors(path: str, check_n: int = 24, min_cos: float = 0.999):
    z = np.load(path, allow_pickle=False)
    ids, hashes, vecs = list(z["ids"]), list(z["hashes"]), z["vectors"].astype(np.float32)
    model = str(z["model"]) if "model" in z else "?"
    print(f"Fayl: {len(ids)} vektor, o'lcham {vecs.shape[1]}, model {model}, dtype {z['vectors'].dtype}")
    if model != MODEL:
        raise SystemExit(f"Model mos emas: {model} != {MODEL}")

    chunks = {c["chunk_id"]: c for c in _load_chunks()}
    missing = [i for i in chunks if i not in set(ids)]
    stale = [i for i, h in zip(ids, hashes) if i not in chunks or _hash(chunks[i]["text"]) != h]
    print(f"chunks.jsonl: {len(chunks)}; faylda yo'q: {len(missing)}; matni o'zgargan/eskirgan: {len(stale)}")
    if stale:
        raise SystemExit("Vektorlar eski chunks.jsonl dan hisoblangan. Qayta export-colab qiling.")

    # 1) Sifat tekshiruvi: shu Mac'dagi ONNX modeli bilan tasodifiy chunklarni qayta hisoblash
    pos = {i: k for k, i in enumerate(ids)}
    rnd = random.Random(42)
    sample = rnd.sample(ids, min(check_n, len(ids)))
    local = np.array(embed_passages(MODEL, [chunks[i]["text"] for i in sample], batch_size=1), dtype=np.float32)
    colab = vecs[[pos[i] for i in sample]]
    cos = (local * colab).sum(1) / (np.linalg.norm(local, axis=1) * np.linalg.norm(colab, axis=1))
    print(f"Mahalliy ONNX vs Colab GPU, {len(sample)} chunk: cosine min={cos.min():.6f} "
          f"o'rtacha={cos.mean():.6f}")
    if cos.min() < min_cos:
        raise SystemExit(f"Vektorlar mos emas (min cosine {cos.min():.4f} < {min_cos}). Import qilinmadi.")

    # 2) ChromaDB ga yozish
    col = get_collection(MODEL)
    step = 500
    for k in tqdm(range(0, len(ids), step), desc="chroma import"):
        bid = ids[k:k + step]
        bc = [chunks[i] for i in bid]
        col.upsert(ids=bid, embeddings=vecs[k:k + step].tolist(),
                   documents=[c["text"] for c in bc], metadatas=[_meta(c) for c in bc])
    extra = set(col.get(include=[])["ids"]) - set(chunks)
    if extra:
        col.delete(ids=list(extra))
    print(f"Tayyor: kolleksiyada {col.count()} chunk (chunks.jsonl: {len(chunks)})")
    (config.STATE / "colab_import.json").write_text(json.dumps({
        "file": path, "n": len(ids), "cos_min": float(cos.min()), "cos_mean": float(cos.mean()),
        "checked": len(sample), "collection_count": col.count()}, indent=1), encoding="utf-8")
