"""Matnni normallashtirish: Unicode, oʻ/gʻ va tutuq belgisi, bo'sh joylar."""
from __future__ import annotations

import re
import unicodedata

OKINA = "\u02bb"   # ʻ  (oʻ, gʻ) - rasmiy lotin alifbosidagi belgi
TUTUQ = "\u02bc"   # ʼ  (maʼno, taʼlim)
APOS = "'`\u00b4\u2018\u2019\u02bb\u02bc\u2032\u02b9\u055a"

_ws = re.compile(r"[ \t\u00a0\u2000-\u200a\u202f\u205f\u3000]+")
_zero = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_og = re.compile(rf"([OoGg])[{APOS}]")
# tutuq: harflar orasidagi apostrof, lekin o/g dan keyingisi emas (u allaqachon ʻ ga aylangan)
_tutuq = re.compile(rf"(?<=[A-Za-z\u00c0-\u024f])(?<![OoGg])[{APOS}](?=[A-Za-z\u00c0-\u024f])")

SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def normalize_apostrophes(s: str) -> str:
    s = _og.sub(lambda m: m.group(1) + OKINA, s)
    s = _tutuq.sub(TUTUQ, s)
    return s


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = _zero.sub("", s)
    s = normalize_apostrophes(s)
    s = s.replace("\r", "")
    s = _ws.sub(" ", s)
    lines = [ln.strip() for ln in s.split("\n")]
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # tinish belgisidan oldingi bo'sh joy: "so'z ." -> "so'z."
    s = re.sub(r" +([,.;:!?»”)])", r"\1", s)
    s = re.sub(r"([«“(]) +", r"\1", s)
    return s.strip()


def to_superscript(digits: str) -> str:
    return digits.translate(SUP)
