"""O'zbek kirill <-> lotin transliteratsiyasi.

cyr_to_lat: kirillcha savol -> lotin (qidiruv uchun).
lat_to_cyr: LLM lotinda yozgan javob -> o'zbek kirill (savol kirillcha bo'lsa). [n] iqtiboslar, raqamlar,
havolalar va rim raqamlari o'zgarmaydi. Brauzerdagi nusxasi: web/src/textproc.ts (bir xil qoidalar,
scripts/test_stage2.py ikkalasini bir xil misollarda solishtiradi).
"""
from __future__ import annotations

import re

_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "gʻ", "д": "d", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "қ": "q", "л": "l", "м": "m", "н": "n", "о": "o", "ў": "oʻ",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ҳ": "h", "ц": "s",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "ʼ", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
VOWELS = set("аеёиоуўэюяaeiou")


def cyr_to_lat(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        low = ch.lower()
        prev = text[i - 1].lower() if i > 0 else " "
        if low == "е":
            # so'z boshida va unlidan keyin "ye": Ер -> Yer, иерархия -> iyerarxiya
            lat = "ye" if (not prev.isalpha() or prev in VOWELS or prev in "ъь") else "e"
        elif low == "ц":
            lat = "s" if not prev.isalpha() else "ts"
        else:
            lat = _MAP.get(low)
            if lat is None:
                out.append(ch)
                continue
        if ch != low and lat:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            lat = lat.upper() if (nxt.isupper() and len(lat) > 1) else lat[0].upper() + lat[1:]
        out.append(lat)
    return re.sub(r"\s+", " ", "".join(out))


# ---------------------------------------------------------------- lotin -> kirill
_L2C = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ", "i": "и", "j": "ж", "k": "к",
    "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "x": "х", "y": "й", "z": "з", "c": "к", "w": "в",
}
_OKINA = "ʻ'‘’`´"          # oʻ, gʻ belgisi (har xil yozilishi)
_TUTUQ = "ʼ"                # maʼno -> маъно
_LAT_VOW = set("aeiouAEIOU")
# o'zgarmaydigan bo'laklar: havola, [n], rim raqami (IV bob), lex.uz
_KEEP = re.compile(r"https?://\S+|www\.\S+|lex\.uz\S*|\[\d+(?:\s*[,;]\s*\d+)*\]|\b[IVXL]{1,6}\b(?=[\s.,;:)\-]|$)")
_TS = re.compile(r"ts(?=iya|ion|ent|ikl|irk)", re.I)


def _l2c_word(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        low = ch.lower()
        nxt = s[i + 1] if i + 1 < n else ""
        prev = s[i - 1] if i > 0 else ""
        up = ch.isupper()
        # ikkinchi harf ham katta bo'lsa (SH, OʻZBEKISTON) - butun so'z katta deb olinadi
        word_up = up and (nxt.isupper() or (prev.isupper() if prev else False))
        cyr, step = None, 1
        if low in "og" and nxt and nxt in _OKINA:
            cyr, step = ("ў" if low == "o" else "ғ"), 2
        elif low == "s" and nxt.lower() == "h":
            cyr, step = "ш", 2
        elif low == "c" and nxt.lower() == "h":
            cyr, step = "ч", 2
        elif low == "y" and nxt.lower() in ("o", "u", "a", "e") and not (nxt.lower() == "o" and i + 2 < n and s[i + 2] in _OKINA):
            v = nxt.lower()
            if v == "e":
                # ye: so'z boshida va unlidan keyin "е", undosh + ye (obyekt) -> "ъе"
                cyr = "е" if (not prev.isalpha() or prev in _LAT_VOW) else "ъе"
            else:
                cyr = {"o": "ё", "u": "ю", "a": "я"}[v]
            step = 2
        elif low == "t" and _TS.match(s, i):
            cyr, step = "ц", 2
        elif low == "e":
            cyr = "э" if (not prev.isalpha() or prev in _LAT_VOW) else "е"
        elif ch == _TUTUQ or (ch in _OKINA and prev.isalpha() and nxt.isalpha()):
            cyr = "ъ"
        else:
            cyr = _L2C.get(low)
        if cyr is None:
            out.append(ch)
            i += 1
            continue
        if up:
            cyr = cyr.upper() if word_up else cyr[0].upper() + cyr[1:]
        out.append(cyr)
        i += step
    return "".join(out)


def lat_to_cyr(text: str) -> str:
    """O'zbek lotin -> kirill. Bo'sh joylar va qator tuzilishi saqlanadi (cyr_to_lat dan farqli)."""
    out, last = [], 0
    for m in _KEEP.finditer(text):
        out.append(_l2c_word(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_l2c_word(text[last:]))
    return "".join(out)


class LatToCyrStream:
    """Oqim uchun: faqat to'liq so'zlar o'giriladi (Sh, oʻ kabi juftliklar bo'laklar orasida uzilmasin)."""

    def __init__(self):
        self.buf = ""

    def feed(self, piece: str) -> str:
        self.buf += piece
        cut = max(self.buf.rfind(" "), self.buf.rfind("\n"))
        if cut < 0:
            return ""
        done, self.buf = self.buf[:cut + 1], self.buf[cut + 1:]
        return lat_to_cyr(done)

    def flush(self) -> str:
        done, self.buf = self.buf, ""
        return lat_to_cyr(done)
