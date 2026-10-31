"""O'zbek kirill -> lotin transliteratsiyasi (foydalanuvchi savoli uchun)."""
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
