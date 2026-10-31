"""Javob ishonchliligi: har gap/da'vo manbada asosi bormi (LLM'siz, qo'shimcha so'rovsiz).

lexrag/verify.py saytdagi jonli matnni bazadagi nusxa bilan solishtiradi (yig'ish sifati); bu modul esa
LLM javobini u iqtibos qilgan moddalar bilan solishtiradi. Har da'vo uchun:
  * raqamlar: javobdagi har raqam (muddat, summa, yosh) iqtibos qilingan modda matnida bormi.
    Manbada so'z bilan yozilgan raqamlar ham hisobga olinadi ("yigirma bir" = 21);
  * leksik moslik: da'vodagi so'zlarning (qisqartirilgan o'zak) qancha qismi moddada bor;
  * ma'no o'xshashligi: bge-m3 embedding (da'vo vs modda; modda vektori indeksdan olinadi).
Ruscha javobda leksik moslik ishlamaydi (manba o'zbekcha) - faqat raqamlar va embedding.
Kirill javob avval lotinga o'giriladi.
"""
from __future__ import annotations

import re

import numpy as np

from .indexer import embed_query
from .lang import NOT_FOUND_RE
from .normalize import normalize_text
from .retrieval import MODEL, get_chunks
from .translit import cyr_to_lat

MAX_CLAIMS = 14
STEM = 5
# chegaralar: scripts/test_stage2.py dagi to'g'ri / buzilgan da'volar bilan tanlangan
LEX_OK, COS_OK, COS_OK_RU = 0.5, 0.66, 0.64
COS_WEAK = 0.62  # bundan past - leksik moslik bo'lsa ham shubhali

_CITE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
_WORD = re.compile(r"[a-zʻʼа-яёўқғҳ0-9]+", re.I)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
STOP = set("""va yoki hamda bilan uchun boʻyicha boʻlgan boʻladi boʻlsa boʻlib esa ham bu shu u ular
ushbu mazkur kabi har bir koʻra asosan qilib etib deb emas lekin ammo agar biroq kerak mumkin
modda moddasi moddasiga moddasida kodeksi kodeksining qonuni qonunining respublikasi oʻzbekiston
respublikasining hisoblanadi belgilanadi nazarda tutilgan tutiladi quyidagi quyidagilar
qisqa javob xulosa tafsilotlar batafsil masalan""".split())

_UNITS = {"bir": 1, "ikki": 2, "uch": 3, "toʻrt": 4, "besh": 5, "olti": 6, "yetti": 7, "sakkiz": 8, "toʻqqiz": 9}
_TENS = {"oʻn": 10, "yigirma": 20, "oʻttiz": 30, "qirq": 40, "ellik": 50, "oltmish": 60, "yetmish": 70,
         "sakson": 80, "toʻqson": 90}


def _num_words(text: str, claim: bool = False) -> set[str]:
    """'yigirma bir kalendar kun' -> {'21'}; 'oʻn sakkiz yoshga' -> {'18'}; 'bir yuz' -> {'100'}.
    claim=True: yolg'iz "bir" (har bir, bir xil) raqam hisoblanmaydi."""
    out: set[str] = set()
    toks = re.findall(r"[a-zʻʼ]+", text.lower())
    i = 0
    while i < len(toks):
        val, used = 0, 0
        cur = 0
        while i + used < len(toks):
            w = re.sub(r"(inchi|nchi|tadan|tasi|ta|ga|da|dan|ni|ning)$", "", toks[i + used])
            if w in _TENS:
                cur += _TENS[w]
            elif w in _UNITS:
                cur += _UNITS[w]
            elif w == "yuz":
                cur = (cur or 1) * 100
            elif w == "ming":
                val += (cur or 1) * 1000
                cur = 0
            else:
                break
            used += 1
        if used and not (claim and used == 1 and val + cur == 1):
            out.add(str(val + cur))
            i += used
        else:
            i += 1
    return out


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM.findall(text)}


def _stems(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall(normalize_text(text).lower()):
        if w in STOP or w.isdigit() or len(w) < 3:
            continue
        out.add(w[:STEM])
    return out


def split_claims(text: str) -> list[tuple[int, int, str]]:
    """(boshi, oxiri, gap) - asl matndagi o'rinlar bilan (brauzer aynan shu gapni belgilaydi)."""
    out = []
    pos = 0
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        # gap oxiri: . ! ? (iqtibosdan keyin ham), keyin bo'sh joy va katta harf / raqam
        for m in re.finditer(r".+?(?:[.!?](?:\s*\[\d+(?:\s*[,;]\s*\d+)*\])*(?=\s+[A-ZА-ЯЁЎҚҒҲ0-9«\"(*])|$)", line):
            s = m.group(0)
            # ro'yxat / sarlavha belgisi belgilanadigan qismga kirmaydi (brauzer markdown'ni buzmasin)
            lead = len(re.match(r"\s*(?:(?:[-*•]|\d+[.)]|#{1,6})\s+)?", s).group(0))
            a, b = start + m.start() + lead, start + m.end()
            if b > a:
                out.append((a, b, text[a:b]))
    return out


def _clean(s: str) -> str:
    s = re.sub(r"^\s*(?:[-*•]|\d+[.)]|#{1,6})\s+", "", s)
    return _CITE.sub(" ", s.replace("**", "")).strip()


def _cos(a, b) -> float:
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def check(text: str, chunk_ids: list[str], lang: str = "uz") -> dict:
    """text - foydalanuvchi ko'rgan javob; chunk_ids - manbalar tartibida ([n] = chunk_ids[n-1])."""
    hits = get_chunks(chunk_ids, embeddings=True)
    by_n = {i + 1: h for i, h in enumerate(hits)}
    src_num = {n: _numbers(h["text"]) | _num_words(h["text"]) for n, h in by_n.items()}
    src_stem = {n: _stems(h["text"]) for n, h in by_n.items()}
    all_num = set().union(*src_num.values()) if src_num else set()

    claims = []
    for a, b, raw in split_claims(text):
        body = _clean(raw)
        if NOT_FOUND_RE.search(body) or len(_WORD.findall(body)) < 4 or (body.endswith(":") and not _NUM.search(body)):
            continue
        cites = sorted({int(x) for m in _CITE.finditer(raw) for x in re.split(r"\s*[,;]\s*", m.group(1))} & set(by_n))
        claims.append({"start": a, "end": b, "body": body, "cites": cites})
    claims = claims[:MAX_CLAIMS]

    for c in claims:
        lat = cyr_to_lat(c["body"]) if lang == "uz_cyr" else c["body"]
        refs = c["cites"] or list(by_n)
        reasons = []
        # raqamlar (iqtibos raqamlari allaqachon olib tashlangan)
        nums = _numbers(lat) | (_num_words(lat, claim=True) if lang != "ru" else set())
        ref_num = set().union(*(src_num[n] for n in refs)) if refs else set()
        missing = sorted(n for n in nums if n not in ref_num)
        if missing:
            elsewhere = [n for n in missing if n in all_num]
            reasons.append(f"{', '.join(missing[:3])} raqami " + ("boshqa manbada bor, iqtibos qilinganida yoʻq"
                                                                    if elsewhere and len(elsewhere) == len(missing)
                                                                    else "manbada yoʻq"))
        # leksik moslik
        st = _stems(lat)
        lex = None
        if lang != "ru" and st:
            lex = max(len(st & src_stem[n]) / len(st) for n in refs) if refs else 0.0
        # ma'no o'xshashligi
        emb = embed_query(MODEL, lat)
        cos = max((_cos(emb, by_n[n]["embedding"]) for n in refs), default=0.0)
        cos_ok = COS_OK_RU if lang == "ru" else COS_OK
        supported = (lex is not None and lex >= LEX_OK and cos >= COS_WEAK) or cos >= cos_ok
        if not supported:
            reasons.append("iqtibos qilingan moddada oʻxshash mazmun topilmadi" if c["cites"]
                           else "iqtibossiz va manbalarda oʻxshashi topilmadi")
        if not c["cites"] and supported and not missing:
            reasons.append("iqtibossiz, lekin manbalarda asosi bor")
        c.update(ok=supported and not missing, lex=None if lex is None else round(lex, 2), cos=round(cos, 3),
                 reasons=reasons)

    checked = len(claims)
    good = sum(c["ok"] for c in claims)
    bad_num = sum(1 for c in claims if any("raqami" in r for r in c["reasons"]))
    if not checked:
        level = None
    else:
        ratio = good / checked
        level = "high" if ratio >= 0.85 and not bad_num else "medium" if ratio >= 0.6 and bad_num <= 1 else "low"
    return {"level": level, "checked": checked, "supported": good,
            "claims": [{"start": c["start"], "end": c["end"], "ok": c["ok"], "cites": c["cites"], "lex": c["lex"],
                        "cos": c["cos"], "reasons": c["reasons"]} for c in claims]}
