"""Tasodifiy hujjatlarni saytdagi jonli matn bilan solishtirish.

Parserdan mustaqil bo'lishi uchun sahifa qayta yuklanadi va `#divCont` ning BUTUN matni
(selectolax bilan, hech qanday klass filtrisiz) olinadi. So'ng:
  * recall    - saytdagi so'zlarning qancha qismi bizning natijada bor
                (matn + o'zgartirish izohlari + LexUZ sharhlari + rekvizit/imzo);
  * precision - bizning asosiy matndagi so'zlarning qanchasi saytda bor;
  * raw_same  - jonli sahifa matni data/raw/ dagi nusxa bilan bir xilmi (yangi tahrir chiqmaganmi).
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from . import config
from .http import PoliteClient
from .normalize import normalize_text, to_superscript
from .scraper import raw_doc_path

UI_STRINGS = ["Hujjatga taklif yuborish", "Audioni tinglash", "Hujjat elementidan havola olish",
              "LexUZ sharhi", "Oldingi tahrirga qarang."]
WORD = re.compile(r"[\wʻʼ¹²³⁴⁵⁶⁷⁸⁹⁰]+", re.U)


def site_text(html: str) -> str:
    # <sup>1</sup> -> ¹ (bizning matnda ham shunday), aks holda "14¹" saytda "141" bo'lib qoladi
    html = re.sub(r"<sup>\s*(\d+)\s*</sup>", lambda m: to_superscript(m.group(1)), html, flags=re.I)
    tree = HTMLParser(html)
    node = tree.css_first("#divCont")
    if node is None:
        return ""
    # Ataylab olib tashlanadigan yagona narsa: har modda yonidagi yashirin klassifikator kodlari
    # (INDEXES_ON_REF, saytda display:none). Hujjat darajasidagisi metadata'da saqlanadi.
    for n in node.css(".INDEXES_ON_REF"):
        n.decompose()
    t = node.text(separator="\n")
    for s in UI_STRINGS:
        t = t.replace(s, " ")
    t = re.sub(r"Oldingi\s+tahrirga\s+qarang\.?", " ", t)  # "oldingi tahrir" navigatsiya havolasi
    return normalize_text(t)


def words(s: str) -> Counter:
    return Counter(w.lower() for w in WORD.findall(s))


def _overlap(a: Counter, b: Counter) -> float:
    tot = sum(a.values())
    return 1.0 if tot == 0 else sum(min(c, b[w]) for w, c in a.items()) / tot


def verify_doc(doc: dict, client: PoliteClient) -> dict:
    live_html = client.get(doc["url"]).text
    live = site_text(live_html)
    raw = site_text(raw_doc_path(doc["lex_id"]).read_text(encoding="utf-8"))
    ours_all = "\n".join(
        [doc["text"], doc.get("title") or "", doc.get("doc_type_full") or ""]
        + [a["text"] for a in doc["amendments"]] + [n["text"] for n in doc["lexuz_notes"]]
        + doc["grif"] + doc["signature"] + doc["publication_source"] + doc["classifiers"])
    lw, ow, bw = words(live), words(ours_all), words(doc["text"])
    missing = [w for w, c in (lw - ow).most_common(15)]
    extra = [w for w, c in (bw - lw).most_common(10)]
    # bitta modda bo'yicha ko'z bilan ko'rish uchun namuna
    arts = [b for b in doc["structure"] if b["kind"] == "article" and b["paras"]]
    sample = random.choice(arts) if arts else None
    return {
        "id": doc["id"], "title": doc["title"], "url": doc["url"],
        "live_words": sum(lw.values()), "our_body_words": sum(bw.values()),
        "recall": round(_overlap(lw, ow), 4),
        "precision": round(_overlap(bw, lw), 4),
        "raw_same_as_live": raw == live,
        "top_missing_words": missing,
        "top_extra_words": extra,
        "sample_article": ({"number": sample["number"], "url": f"{doc['url']}#{sample['anchor']}",
                            "our_text": "\n".join(sample["paras"])[:600]} if sample else None),
    }


def verify_random(n: int = 4, seed: int | None = None):
    files = sorted(config.CLEAN.glob("*.json"))
    rnd = random.Random(seed)
    pick = rnd.sample(files, min(n, len(files)))
    client = PoliteClient()
    results = []
    for p in pick:
        doc = json.loads(p.read_text(encoding="utf-8"))
        r = verify_doc(doc, client)
        results.append(r)
        print(f"{r['id']:>9}  recall={r['recall']:.3f}  precision={r['precision']:.3f}  "
              f"raw==live={r['raw_same_as_live']}  {r['title'][:60]}")
        if r["top_missing_words"]:
            print("           saytda bor, bizda yo'q so'zlar:", r["top_missing_words"][:10])
        if r["top_extra_words"]:
            print("           bizda bor, saytda yo'q so'zlar:", r["top_extra_words"][:10])
    (config.STATE / "verify.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results
