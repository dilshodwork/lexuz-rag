"""eval/questions.jsonl ni kengaytirish va dev/test bo'lish (4-bosqich, bir martalik).

    .venv/bin/python scripts/build_eval_set.py /tmp/dalil_q/part_a.jsonl ... [--seed 20261101]

* Eski 50 savol saqlanadi (matni va gold o'zgarmaydi), ularga "lang" (haqiqiy til) yorlig'i qo'shiladi.
* Yangi savollar (part_*.jsonl): id, question, category, difficulty, lang, gold, evidence. evidence - gold modda
  matnidan qisqa iqtibos (savolni yozgan kishi moddani o'qiganini tekshirish uchun); to'plamga "evidence" sifatida
  saqlanadi.
* split: dev / test, tasodifiy (seed), (kategoriya, til) qatlamlari bo'yicha muvozanatli: har qatlam aralashtiriladi
  va navbat bilan taqsimlanadi, kichik qatlamlarda boshlang'ich tomon hozircha kamroq savoli bor qism.
  "Bazada yo'q" savollar alohida qatlam (til bo'yicha).
* Har gold modda data/chunks.jsonl da borligi, amaldagi va o'zgartirish qonuni emasligi tekshiriladi; evidence
  iqtibosi gold moddalardan birining matnida borligi tekshiriladi.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag.lang import detect_lang  # noqa: E402

QFILE = ROOT / "eval" / "questions.jsonl"

# 5 ta yangi "bazada yo'q" savol: chet el qonuni (javobi O'zbekiston qonunlarida yo'q, lekin mavzusi yaqin - eng
# qiyin holat), umumiy savol va bazada yo'q soha (narxlar qonunda belgilanmaydi)
NONE_NEW = [
    {"id": "n05", "question": "Rossiyada yillik mehnat ta'tili necha kun beriladi?", "lang": "uz"},
    {"id": "n06", "question": "AQShda mashina haydash guvohnomasini necha yoshdan olish mumkin?", "lang": "uz"},
    {"id": "n07", "question": "Toshkent metrosida bir martalik yo'l haqi hozir qancha turadi?", "lang": "uz"},
    {"id": "n08", "question": "Қозоғистонда аёллар неча ёшда пенсияга чиқади?", "lang": "uz_cyr"},
    {"id": "n09", "question": "Какой смартфон лучше купить до 300 долларов?", "lang": "ru"},
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def load_articles() -> dict:
    arts: dict = defaultdict(lambda: {"text": "", "ok": False})
    with open(ROOT / "data" / "chunks.jsonl", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            a = arts[(c["doc_id"], c.get("article_number") or "")]
            a["text"] += " " + c["text"]
            if c.get("status") == "amalda" and str(c.get("is_amending_law")) in ("False", "false", "0", "None", ""):
                a["ok"] = True
    return arts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--seed", type=int, default=20261101)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    old = [json.loads(l) for l in QFILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    old = [q for q in old if q["id"][:1] != "n" or q["id"] in ("n01", "n02", "n03", "n04")]
    old = [q for q in old if not re.match(r"^(a\d|b\d|c1\d\d|d\d|n0[5-9])", q["id"])]   # qayta ishga tushirilsa
    for q in old:
        q.setdefault("lang", detect_lang(q["question"]))     # eski 50 ta: aniqlangan til = haqiqiy (qo'lda tekshirildi)
    new = []
    for p in a.parts:
        for l in Path(p).read_text(encoding="utf-8").splitlines():
            if l.strip():
                new.append(json.loads(l))
    for n in NONE_NEW:
        new.append({**n, "category": "bazada yoʻq", "difficulty": "oson" if n["id"] != "n05" else "qiyin", "gold": []})
    qs = old + new

    # tekshiruv
    arts = load_articles()
    errs = []
    ids = Counter(q["id"] for q in qs)
    errs += [f"takror id: {i}" for i, c in ids.items() if c > 1]
    texts = Counter(_norm(q["question"]) for q in qs)
    errs += [f"takror savol: {t}" for t, c in texts.items() if c > 1]
    for q in qs:
        if q["lang"] not in ("uz", "uz_cyr", "ru") or q["difficulty"] not in ("oson", "o'rta", "qiyin"):
            errs.append(f"{q['id']}: lang/difficulty {q['lang']} {q['difficulty']}")
        for g in q["gold"]:
            art = arts.get((g["doc_id"], g["article"]))
            if not art:
                errs.append(f"{q['id']}: {g['doc_id']} {g['article']} yoʻq")
            elif not art["ok"]:
                errs.append(f"{q['id']}: {g['doc_id']} {g['article']} amalda emas / oʻzgartirish qonuni")
        ev = q.get("evidence")
        if ev:
            pieces = [x for x in re.split(r"\s*…\s*", ev) if x.strip()]
            for piece in pieces:
                if not any(_norm(piece.strip(" .,;")) in _norm(arts[(g["doc_id"], g["article"])]["text"])
                           for g in q["gold"]):
                    errs.append(f"{q['id']}: evidence moddada topilmadi: {piece[:60]}")
    if errs:
        print("\n".join(errs))
        raise SystemExit(1)

    # split: (kategoriya, til) qatlamlari
    rnd = random.Random(a.seed)
    strata: dict = defaultdict(list)
    for q in qs:
        strata[(q["category"], q["lang"])].append(q)
    cnt = Counter()       # (til, split) va (None, split)
    keys_ = sorted(strata)
    rnd.shuffle(keys_)
    for key in keys_:
        group = strata[key]
        rnd.shuffle(group)
        lang = key[1]
        # toq qatlamda ortiqcha savol shu tilda (teng bo'lsa - umumiy) kamroq savoli bor qismga
        d = (cnt[(lang, "dev")] - cnt[(lang, "test")]) or (cnt[(None, "dev")] - cnt[(None, "test")])
        first = rnd.choice(["dev", "test"]) if d == 0 else ("test" if d > 0 else "dev")
        other = "test" if first == "dev" else "dev"
        for i, q in enumerate(group):
            q["split"] = first if i % 2 == 0 else other
            cnt[(lang, q["split"])] += 1
            cnt[(None, q["split"])] += 1

    order = {q["id"]: i for i, q in enumerate(qs)}
    qs.sort(key=lambda q: order[q["id"]])
    keys = ["id", "question", "category", "difficulty", "lang", "split", "gold", "evidence"]
    lines = [json.dumps({k: q[k] for k in keys if k in q}, ensure_ascii=False) for q in qs]
    print(f"jami {len(qs)}: split {dict(Counter(q['split'] for q in qs))}")
    print("til:", dict(Counter(q["lang"] for q in qs if q["gold"])), "| yoʻq:", dict(Counter(q["lang"] for q in qs if not q["gold"])))
    print("til × split:", dict(Counter((q["lang"], q["split"]) for q in qs)))
    print("kategoriya:", dict(Counter(q["category"] for q in qs)))
    print("qiyinlik:", dict(Counter(q["difficulty"] for q in qs)))
    det = [(q["id"], q["lang"], detect_lang(q["question"])) for q in qs if detect_lang(q["question"]) != q["lang"]]
    print("til aniqlash xatolari (joriy lang.detect_lang):", det)
    if not a.dry:
        QFILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("yozildi:", QFILE)


if __name__ == "__main__":
    main()
