"""Murakkab savolni 2-3 ta kichik qidiruvga bo'lish.

Standart holatda LLM'siz evristika (Gemini bepul tarifi kuniga ~20 so'rov, har savolga qo'shimcha so'rov
qimmat): bir nechta savol belgisi, "va" / "hamda" / "shuningdek" bilan bog'langan ikki savol qismi, uzunlik.
To'liq savol ham har doim qidiriladi; natijalar RRF bilan birlashtiriladi (rag.search).

LLM bilan rejalashtirish faqat ixtiyoriy: .env da LLM_PLAN=1 (server kaliti yo'lida, standart o'chiq).
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

MAX_PARTS = 3
# savol so'zlari: bo'lingan qism mustaqil savol bo'lishi uchun kamida bittasi kerak
_QW = re.compile(
    r"\b(qanday|qancha|necha|nechta|nima|nimalar|kim|kimlar|qachon|qayerda|qayerga|qaysi|nega|"
    r"mumkinmi|kerakmi|boʻladimi|bormi|\w+mi|"
    r"қандай|қанча|неча|нима|ким|қачон|қаерда|қайси|нега|мумкинми|керакми|"
    r"как|какой|какая|какие|сколько|что|кто|когда|где|можно|нужно|ли)\b", re.I)
_CONJ = re.compile(r"\s*(?:,?\s+(?:va|hamda|shuningdek|ва|ҳамда|шунингдек|а также|и)\s+|;\s*)", re.I)


def _words(s: str) -> int:
    return len(re.findall(r"\w+", s))


def _clean(s: str) -> str:
    return s.strip(" ,;.").strip()


_PRON = re.compile(r"^(uni|u|unga|uning|bunda|buning|buni|ularni|его|её|ее|это|их|ему|уни|у|унга|буни)\b\s*", re.I)


def _topic(part: str) -> str:
    """Birinchi qismning mavzusi: savol so'zigacha bo'lgan so'zlar ("Ijara shartnomasi qanday ..." -> "Ijara shartnomasi")."""
    words = part.rstrip("?").split()
    head = []
    for w in words[:4]:
        if _QW.fullmatch(w.lower()):
            break
        head.append(w)
    return " ".join(head or words[:2])


def _context(parts: list[str]) -> list[str]:
    """'Uni bo'lib olish mumkinmi?' kabi olmosh bilan boshlangan qismga oldingi qismning boshi qo'shiladi."""
    out = []
    for i, p in enumerate(parts):
        if i and _PRON.match(p):
            p = f"{_topic(parts[0])} {_PRON.sub('', p)}"
        out.append(p[:1].upper() + p[1:])
    return out


def split_question(q: str) -> list[str]:
    """[] - bo'linmaydi (oddiy savol). Aks holda 2-3 ta kichik savol."""
    return _context(_split(q))


def _split(q: str) -> list[str]:
    q = re.sub(r"\s+", " ", q).strip()
    if _words(q) < 6:
        return []
    # 1) bir nechta savol belgisi: "...necha kun? Qanday hujjatlar kerak?"
    parts = [_clean(p) for p in re.split(r"(?<=\?)\s*", q) if _words(p) >= 2]
    if len(parts) >= 2:
        return [p if p.endswith("?") else p + "?" for p in parts][:MAX_PARTS]
    # 2) bog'lovchi: ikki tomoni ham savol so'zli va kamida 3 so'zli bo'lsa
    if _words(q) < 8:
        return []
    pieces = [_clean(p) for p in _CONJ.split(q) if p and _clean(p)]
    if len(pieces) < 2:
        return []
    good = [p for p in pieces if _words(p) >= 3 and _QW.search(p)]
    if len(good) < 2 or len(good) != len(pieces):
        # "ota va ona" kabi otlar bog'lanishi: bo'linmaydi. Faqat oxirgi qism qisqa bo'lsa, oldingi kontekst qo'shiladi
        if len(pieces) == 2 and _QW.search(pieces[1]) and _QW.search(pieces[0]) and _words(pieces[0]) >= 3:
            head = " ".join(pieces[0].split()[:3])
            return [pieces[0] + "?", f"{head} {pieces[1]}".rstrip("?") + "?"]
        return []
    return [p.rstrip("?") + "?" for p in good][:MAX_PARTS]


PLAN_SYSTEM = ("Foydalanuvchi savolini qonunchilik bazasidan qidirish uchun 1-3 ta qisqa mustaqil qidiruv "
               "soʻroviga ajrat (oʻzbek lotinda). Faqat JSON roʻyxat qaytar, masalan: [\"...\", \"...\"]. "
               "Savol oddiy boʻlsa, bitta element.")


def llm_enabled() -> bool:
    return os.environ.get("LLM_PLAN", "").strip() in ("1", "true", "yes")


def llm_split(q: str) -> list[str]:
    """Ixtiyoriy (LLM_PLAN=1): LLM bilan bo'lish. Xato bo'lsa evristikaga qaytiladi."""
    from . import llm
    try:
        raw = llm.complete(PLAN_SYSTEM, q, max_tokens=512)
        items = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
        items = [str(x).strip() for x in items if str(x).strip()][:MAX_PARTS]
        return items if len(items) >= 2 else []
    except Exception as e:  # noqa: BLE001
        log.warning("LLM rejalashtirish ishlamadi (%s), evristika ishlatiladi", type(e).__name__)
        return split_question(q)
