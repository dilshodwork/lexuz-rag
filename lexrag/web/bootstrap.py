"""Konteyner ishga tushganda qidiruv indeksini tayyorlash (Hugging Face Spaces).

data/index (ChromaDB ~736 MB + BM25 ~30 MB) va data/metadata.csv git'ga kirmaydi. Ular alohida Hugging Face
DATASET repo'da turadi (scripts/hf_deploy.py yuklaydi) va server start'da shu yerga yuklab olinadi:

    HF_DATASET=<user>/dalil-index        # dataset repo (public; private bo'lsa HF_TOKEN ham kerak)
    HF_DATASET_REVISION=main             # ixtiyoriy: aniq commit / tag
    DALIL_SEED_DIR=/seed                 # ixtiyoriy: HF_DATASET o'rniga lokal papkadan nusxa (Docker sinovi)

Indeks DALIL_DATA_DIR da allaqachon bo'lsa (masalan, HF persistent storage /data) hech narsa yuklanmaydi.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from .. import config

log = logging.getLogger("lexrag.web")

# serverga kerakli fayllar (dataset repo ichidagi yo'l = DALIL_DATA_DIR ichidagi yo'l)
REQUIRED = ["index/chroma/chroma.sqlite3", "index/bm25/ids.json", "index/bm25/params.index.json", "metadata.csv"]
PATTERNS = ["index/chroma/**", "index/bm25/**", "metadata.csv"]


def missing() -> list[str]:
    return [p for p in REQUIRED if not (config.DATA / p).is_file()]


def ensure_data(phase=lambda name, detail="": None) -> str:
    """Indeks bo'lmasa yuklab oladi. Qaytaradi: "local" | "dataset" | "seed". Xato bo'lsa RuntimeError."""
    if not missing():
        return "local"
    repo = os.environ.get("HF_DATASET", "").strip()
    seed = os.environ.get("DALIL_SEED_DIR", "").strip()
    t0 = time.time()
    if repo:
        phase("download", "indeks yuklanmoqda")
        from huggingface_hub import snapshot_download
        log.info("Indeks yuklanmoqda: dataset %s -> %s", repo, config.DATA)
        snapshot_download(repo_id=repo, repo_type="dataset", local_dir=str(config.DATA),
                          revision=os.environ.get("HF_DATASET_REVISION") or None,
                          allow_patterns=PATTERNS, token=os.environ.get("HF_TOKEN") or None,
                          max_workers=8)
        src = "dataset"
    elif seed:
        phase("download", "indeks nusxalanmoqda")
        log.info("Indeks nusxalanmoqda: %s -> %s", seed, config.DATA)
        for rel in ("index/chroma", "index/bm25"):
            shutil.copytree(Path(seed) / rel, config.DATA / rel, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".DS_Store"))
        shutil.copy2(Path(seed) / "metadata.csv", config.DATA / "metadata.csv")
        src = "seed"
    else:
        raise RuntimeError("Qidiruv indeksi topilmadi va HF_DATASET sozlanmagan")
    if left := missing():
        raise RuntimeError(f"Indeks to'liq emas: {', '.join(left)}")
    # HF dataset yuklagichi .cache/huggingface papkasini qoldiradi - qidiruvga xalaqit bermaydi
    log.info("Indeks tayyor (%s): %.1fs", src, time.time() - t0)
    return src
