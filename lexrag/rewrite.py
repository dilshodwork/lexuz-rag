"""So'rovni huquqiy atamalarga qayta yozish (query rewriting) - og'zaki savollar uchun.

Muammo (spec-2026-11-19 run): javobi bor savollardagi qidiruv xatolarining deyarli hammasi og'zaki ifodada -
"qarzni undirish uchun sudga murojaat muddati" (qonunda: "da'vo muddati"), "ko'chada baqirib so'kinish"
("mayda bezorilik"). LLM savolni qonun tilidagi qisqa so'rovga aylantiradi; qidiruv asl savol va qayta
yozilgan so'rov bilan alohida bajarilib, RRF bilan birlashtiriladi (rag.prepare_steps).

* Faqat asl savolning eng yaqin moddasi uzoq bo'lsa (cosine < REWRITE_GATE) - aniq savollarga LLM chaqirilmaydi.
* "Bazada yo'q" qarori asl savol bo'yicha qoladi: qayta yozilgan so'rov chet el qonuni haqidagi savolni ham
  o'zbek moddasiga yaqinlashtirib yuborishi mumkin.
* Natija keshda (DALIL_DATA_DIR/state/rewrite_cache.json): bir xil savol - bir xil so'rov (takrorlanuvchanlik,
  kvota tejaladi).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading

from . import config, llm

log = logging.getLogger(__name__)

REWRITE_GATE = 0.64   # DEV: shu chegaradan past 37/81 savol, ularda 13 ta xatoning 11 tasi

SYSTEM = """Sen Oʻzbekiston qonunchiligi bazasi (lex.uz) uchun qidiruv soʻrovi yozasan.
Foydalanuvchi savolini qonun matnida ishlatiladigan rasmiy huquqiy atamalar bilan qisqa qidiruv soʻroviga aylantir.
Qoidalar:
- Faqat oʻzbek tilida, lotin yozuvida yoz (savol rus tilida yoki kirillda boʻlsa ham).
- Kundalik soʻzlarni qonun atamasiga almashtir (masalan: "qarzni sud orqali undirish muddati" -> "daʼvo muddati";
  "koʻchada soʻkinish" -> "mayda bezorilik"; "ishdan haydash" -> "mehnat shartnomasini bekor qilish").
- Qaysi hujjatda boʻlishi ehtimolini qoʻsh (masalan: "Fuqarolik kodeksi", "Soliq kodeksi", "... toʻgʻrisidagi qonun").
- Modda raqamini, sonlarni va javobni yozma, faqat qidiruv soʻrovi.
- Bitta qator, 25 soʻzdan oshmasin, izohsiz."""

_lock = threading.Lock()
_cache: dict = {}
_loaded = False


def enabled() -> bool:
    return os.environ.get("QUERY_REWRITE", "1").strip().lower() not in ("0", "false", "no", "")


def _path():
    return config.STATE / "rewrite_cache.json"


def _load() -> dict:
    global _loaded
    if not _loaded:
        try:
            _cache.update(json.loads(_path().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        _loaded = True
    return _cache


def needed(result: dict) -> bool:
    """prepare_steps natijasi bo'yicha: qayta yozish kerakmi (asl qidiruv uzoq, lekin "bazada yo'q" emas)."""
    best = result.get("best_cosine")
    return (enabled() and not result.get("no_answer") and not result.get("parts")
            and best is not None and best < REWRITE_GATE)


def cached(question: str) -> str | None:
    with _lock:
        return _load().get(question.strip())


def rewrite(question: str) -> str | None:
    """Qayta yozilgan so'rov yoki None (LLM xatosi / bo'sh javob - qidiruv asl savol bilan davom etadi)."""
    q = question.strip()
    if hit := cached(q):
        return hit
    try:
        out = llm.complete(SYSTEM, f"Savol: {q}", temperature=0.0, max_tokens=1024, seed=42, deadline_s=20)
    except Exception as e:  # noqa: BLE001 - qayta yozish ixtiyoriy qadam
        log.warning("rewrite xatosi: %s", str(e)[:200])
        return None
    out = re.sub(r"\s+", " ", out.split("<<<", 1)[0]).strip().strip('"«»').strip()
    if not out or len(out) > 400:
        return None
    with _lock:
        c = _load()
        c[q] = out
        try:
            _path().parent.mkdir(parents=True, exist_ok=True)
            tmp = _path().with_suffix(".tmp")
            tmp.write_text(json.dumps(c, ensure_ascii=False, indent=0), encoding="utf-8")
            tmp.replace(_path())
        except OSError as e:
            log.warning("rewrite keshini yozib bo'lmadi: %s", e)
    return out
