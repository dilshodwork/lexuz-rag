"""Ishonch tekshiruvi (trust.check) chegaralarini ruscha javob -> o'zbekcha manba uchun kalibrlash. LLM'siz.

    .venv/bin/python scripts/calibrate_trust.py          # -> eval/trust_calibration.json

Ma'lumotlar:
  * ru_real  - haqiqiy LLM javoblari: eval/answers.json (r01) + eval/answers_ru.json (6 ta, 4-bosqich). Har da'vo
               manba bilan qo'lda solishtirildi - hammasi to'g'ri (eval/README.md).
  * ru_trans - eval/answers.json dagi o'zbekcha javoblar (q02, q14, q28, c03) ning qo'lda qilingan ruscha tarjimasi,
               o'sha manbalar va o'sha [n] bilan (to'g'ri da'volar).
  * uz_real  - o'sha o'zbekcha javoblarning o'zi (regressiya yo'qligini ko'rish uchun).
  * cross    - to'g'ri da'volar boshqa savolning manbalariga bog'lanadi (noto'g'ri manba).
  * false_ru - ataylab yozilgan noto'g'ri da'volar (mavzu va manba to'g'ri, mazmuni / soni noto'g'ri).
answers.json dagi javoblarning manbalari 3-bosqich sozlamalari bilan qayta topiladi (LLM'siz, deterministik) va
yozilgan gold_in_sources bilan solishtiriladi.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag import config, rag, trust, retrieval as R  # noqa: E402

OUT = ROOT / "eval" / "trust_calibration.json"

TRANS = {
    "q02": ("Согласно статье 130 Трудового кодекса, срок предварительного испытания не должен превышать трёх месяцев. "
            "Для руководителей организаций, их заместителей, главных бухгалтеров, а также руководителей обособленных "
            "подразделений организаций этот срок не должен превышать шести месяцев [1]."),
    "q14": ("Согласно статье 99 Семейного кодекса, при отсутствии соглашения между родителями о содержании суд взыскивает "
            "алименты на одного ребёнка в размере одной четверти ежемесячного заработка и (или) иного дохода родителей [1]."
            "\n\nПри этом размер алиментов, взыскиваемых на каждого ребёнка, не должен быть меньше 26,5 процента "
            "минимального размера оплаты труда, установленного законодательством [1]."),
    "q28": ("Доходы физического лица — резидента Республики Узбекистан, в том числе заработная плата, облагаются налогом "
            "по ставке 12 процентов на основании статьи 381 Налогового кодекса [2].\n\nОднако в отдельных случаях ставки "
            "могут отличаться:\n* К заработной плате граждан Республики Узбекистан и лиц без гражданства, являющихся "
            "работниками участников Международного центра цифровых технологий, применяется ставка налога 7,5 процента [5]."
            "\n* Иностранные граждане, признанные высококвалифицированными работниками органов или участников Центра, "
            "освобождаются от уплаты налога на доходы в виде заработной платы [5].\n* К заработной плате иностранных "
            "граждан, не отвечающих критериям высококвалифицированных работников, применяется ставка налога 12 процентов [5]."),
    "c03": ("Президент Республики Узбекистан избирается сроком на семь лет [1][3]. Одно и то же лицо не может быть "
            "Президентом Республики Узбекистан более двух сроков подряд [1][3].\n\n1) Президент избирается сроком на семь "
            "лет [1][3][4].\n2) Одно и то же лицо не может быть Президентом более двух сроков подряд [1][3]."),
}

# (javob id - manbalari shu javobniki, da'vo). Har biri alohida bitta da'voli "javob".
FALSE_RU = [
    ("q02", "Испытательный срок обязателен для всех работников, и отказаться от него нельзя ни в каком случае [1]."),
    ("q02", "Во время испытательного срока работнику не выплачивается заработная плата [1]."),
    ("q14", "Алименты на одного ребёнка составляют половину всех доходов отца [1]."),
    ("q14", "Суд не вправе взыскивать алименты, если родители ребёнка не состояли в браке [1]."),
    ("q28", "Пенсии и стипендии облагаются налогом на доходы по ставке 20 процентов [2]."),
    ("q28", "Работники Международного центра цифровых технологий полностью освобождены от всех налогов [5]."),
    ("c03", "Президент Узбекистана избирается парламентом сроком на пять лет [1]."),
    ("c03", "Президентом может стать гражданин, проживший в Узбекистане не менее одного года [1]."),
    ("a04", "Работодатель вправе удерживать до девяноста процентов зарплаты при каждой выплате [1]."),
    ("a04", "Любые удержания из зарплаты допускаются только с письменного разрешения профсоюза [1]."),
    ("c112", "Административное задержание может длиться до семидесяти двух часов без уведомления прокурора [4]."),
    ("c112", "Задержанного за мелкое хулиганство обязаны немедленно отпустить по требованию родственников [4]."),
    ("c114", "Иностранные автомобили освобождены от обязательного страхования, если находятся в стране менее месяца [1]."),
    ("c123", "За недекларирование товара на таможне предусмотрено лишение свободы на срок до десяти лет [1]."),
    ("d19", "Любая лицензия выдаётся сроком на пять лет и подлежит ежегодному продлению [2]."),
    ("b11", "Несовершеннолетний может открыть вклад в банке только с письменного согласия органов опеки [1]."),
    ("b11", "Подросток с четырнадцати лет может самостоятельно продать квартиру без согласия родителей [1]."),
]


# o'sha noto'g'ri da'volarning o'zbekcha varianti: o'zbekcha qoidalar (COS_OK, LEX_TIERS) ularni qanchasini o'tkazadi -
# ruscha chegara shunga yaqin qattiqlikda bo'lishi kerak
FALSE_UZ = [
    ("q02", "Sinov muddati barcha xodimlar uchun majburiy va undan hech qanday holatda voz kechib boʻlmaydi [1]."),
    ("q02", "Sinov muddati davomida xodimga ish haqi toʻlanmaydi [1]."),
    ("q14", "Bitta bola uchun aliment otaning barcha daromadining yarmini tashkil etadi [1]."),
    ("q14", "Agar ota-ona nikohda boʻlmagan boʻlsa, sud aliment undirishga haqli emas [1]."),
    ("q28", "Pensiya va stipendiyalarga 20 foizlik stavkada daromad soligʻi solinadi [2]."),
    ("q28", "Raqamli texnologiyalar xalqaro markazi xodimlari barcha soliqlardan toʻliq ozod qilingan [5]."),
    ("c03", "Oʻzbekiston Prezidenti parlament tomonidan besh yil muddatga saylanadi [1]."),
    ("c03", "Oʻzbekistonda kamida bir yil yashagan fuqaro Prezident boʻlishi mumkin [1]."),
    ("a04", "Ish beruvchi har bir toʻlovda ish haqining toʻqson foizigacha ushlab qolishga haqli [1]."),
    ("a04", "Ish haqidan har qanday ushlab qolish faqat kasaba uyushmasining yozma ruxsati bilan amalga oshiriladi [1]."),
    ("c112", "Maʼmuriy yoʻl bilan ushlab turish prokurorga xabar bermasdan yetmish ikki soatgacha davom etishi mumkin [4]."),
    ("c112", "Mayda bezorilik uchun ushlangan shaxs qarindoshlari talabi bilan darhol ozod qilinishi shart [4]."),
    ("c114", "Chet el avtomobillari mamlakatda bir oydan kam boʻlsa, majburiy sugʻurtadan ozod qilinadi [1]."),
    ("c123", "Tovarni deklaratsiyalamaganlik uchun oʻn yilgacha ozodlikdan mahrum qilish nazarda tutilgan [1]."),
    ("d19", "Har qanday litsenziya besh yil muddatga beriladi va har yili uzaytirilishi kerak [2]."),
    ("b11", "Voyaga yetmagan shaxs bankda omonat ochishi uchun vasiylik organining yozma roziligi kerak [1]."),
    ("b11", "Oʻsmir oʻn toʻrt yoshdan boshlab ota-onasining roziligisiz kvartirani sota oladi [1]."),
]


def stage3_sources(question: str) -> list[str]:
    """3-bosqich qidiruvi (eski BM25 indeksi, so'z tiklashsiz, ruscha BM25 lug'at+translit) - answers.json manbalari."""
    saved = (R.BM25_DIR, R.REPAIR, R.RU_BM25)
    R.use_bm25_dir(config.INDEX_DIR / "bm25")
    R.REPAIR, R.RU_BM25 = "off", "glossary+translit"
    try:
        return [s["chunk_id"] for s in rag.prepare(question)["sources"]]
    finally:
        R.use_bm25_dir(saved[0])
        R.REPAIR, R.RU_BM25 = saved[1], saved[2]


def load_items() -> list[dict]:
    a3 = json.loads((ROOT / "eval" / "answers.json").read_text(encoding="utf-8"))
    a4 = json.loads((ROOT / "eval" / "answers_ru.json").read_text(encoding="utf-8"))
    items, src = [], {}
    for it in a3["items"]:
        if it["status"] != "ok":
            continue
        ids = stage3_sources(it["question"])
        gold = {(g["doc_id"], g["article"]) for g in it["gold"]}
        meta = R.chunk_meta(ids)
        gis = [i + 1 for i, c in enumerate(ids) if (str(meta[c]["doc_id"]), str(meta[c]["article_number"])) in gold]
        if gis != it["gold_in_sources"]:
            raise SystemExit(f"{it['id']}: manbalar qayta topilmadi ({gis} != {it['gold_in_sources']})")
        src[it["id"]] = ids
        kind = "ru_real" if it["lang"] == "ru" else "uz_real"
        items.append({"id": it["id"], "kind": kind, "lang": it["lang"], "text": it["answer"], "ids": ids, "correct": True})
    for it in a4["items"]:
        if it["status"] == "ok":
            src[it["id"]] = it["chunk_ids"]
            items.append({"id": it["id"], "kind": "ru_real", "lang": "ru", "text": it["answer"], "ids": it["chunk_ids"],
                          "correct": True})
    for qid, t in TRANS.items():
        items.append({"id": qid, "kind": "ru_trans", "lang": "ru", "text": t, "ids": src[qid], "correct": True})
    for i, (qid, t) in enumerate(FALSE_RU):
        items.append({"id": f"{qid}-f{i}", "kind": "false_ru", "lang": "ru", "text": t, "ids": src[qid], "correct": False})
    for i, (qid, t) in enumerate(FALSE_UZ):
        items.append({"id": f"{qid}-fu{i}", "kind": "false_uz", "lang": "uz", "text": t, "ids": src[qid], "correct": False})
    # noto'g'ri manba: har to'g'ri javob keyingi savolning manbalari bilan
    good = [x for x in items if x["correct"]]
    order = sorted(src)
    for x in good:
        other = order[(order.index(x["id"]) + 3) % len(order)]
        items.append({**x, "id": f"{x['id']}>{other}", "kind": "cross_" + ("ru" if x["lang"] == "ru" else "uz"),
                      "ids": src[other], "correct": False})
    return items


def features(items: list[dict]) -> list[dict]:
    """Har da'vo: kontekstsiz va kontekstli cosine, lex, sonlar."""
    rows = []
    ru_words = trust._ru_num_words
    for x in items:
        trust.CONTEXT_ITEMS = False
        trust._ru_num_words = lambda t, claim=False: set()     # 3-bosqich kodi: ruscha son so'zlari tanilmasdi
        o = trust.check(x["text"], x["ids"], x["lang"], "legal", features=True)
        trust._ru_num_words = ru_words
        a = trust.check(x["text"], x["ids"], x["lang"], "legal", features=True)
        trust.CONTEXT_ITEMS = True
        trust.CONTEXT_LANGS = ("ru", "uz", "uz_cyr")
        b = trust.check(x["text"], x["ids"], x["lang"], "legal", features=True)
        for co, ca, cb in zip(o["claims"], a["claims"], b["claims"]):
            f, g = ca["feat"], cb["feat"]
            rows.append({"item": x["id"], "kind": x["kind"], "lang": x["lang"], "correct": x["correct"],
                         "claim": x["text"][ca["start"]:ca["end"]][:160], "cos": round(f["cos"], 4),
                         "cos_ctx": round(g["cos"], 4), "ctx": g["ctx"], "lex": f["lex"], "nums": f["nums"],
                         "missing": f["missing"], "nums_old": co["feat"]["nums"], "missing_old": co["feat"]["missing"]})
    trust.CONTEXT_ITEMS, trust.CONTEXT_LANGS = False, ("ru",)
    return rows


def _nums(r: dict, p: dict):
    return (r["nums_old"], r["missing_old"]) if p.get("old_nums") else (r["nums"], r["missing"])


def supported(r: dict, p: dict) -> bool:
    cos = r["cos_ctx"] if p["ctx"] and (r["lang"] == "ru" or p["ctx_all"]) else r["cos"]
    nums, missing = _nums(r, p)
    num_ok = bool(nums) and not missing
    if missing:
        return False
    if r["lang"] == "ru":
        return cos >= p["ok"] or (num_ok and cos >= p["num"])
    return cos >= trust.COS_OK or (r["lex"] is not None and any(r["lex"] >= lx and cos >= cx for lx, cx in trust.LEX_TIERS))


def rate(rows, p, kinds) -> tuple[int, int]:
    rs = [r for r in rows if r["kind"] in kinds]
    return sum(supported(r, p) for r in rs), len(rs)


def level_of(rows_item, p) -> str | None:
    """trust.check bilan bir xil daraja qoidasi."""
    if not rows_item:
        return None
    good = sum(supported(r, p) for r in rows_item)
    bad_num = sum(1 for r in rows_item if _nums(r, p)[1])
    ratio = good / len(rows_item)
    return "high" if ratio >= 0.85 and not bad_num else "medium" if ratio >= 0.6 and bad_num <= 1 else "low"


def main():
    logging.disable(logging.WARNING)
    items = load_items()
    rows = features(items)
    old = {"ok": 0.64, "num": 1.0, "ctx": False, "ctx_all": False, "old_nums": True}   # 3-bosqich: aynan eski kod
    grid = []
    for ctx in (False, True):
        for ok_ in [round(0.50 + 0.02 * i, 2) for i in range(9)]:          # 0.50 .. 0.66
            for num in [round(0.44 + 0.02 * i, 2) for i in range(10)] + [1.0]:   # 0.44 .. 0.62, 1.0 = o'chiq
                if num > ok_ and num != 1.0:
                    continue
                p = {"ok": ok_, "num": num, "ctx": ctx, "ctx_all": False}
                tp, npos = rate(rows, p, ("ru_real", "ru_trans"))
                fp, nneg = rate(rows, p, ("false_ru", "cross_ru"))
                grid.append({**p, "tpr": round(tp / npos, 4), "fpr": round(fp / nneg, 4), "tp": tp, "fp": fp,
                             "npos": npos, "nneg": nneg, "j": round(tp / npos - fp / nneg, 4)})
    # tanlash: Youden J (TPR - FPR) eng katta; teng bo'lsa - FPR kichigi, keyin chegara kattasi (ehtiyotkor)
    best = max(grid, key=lambda g: (g["j"], -g["fpr"], g["ok"], g["num"]))
    out = {"n_items": len(items), "n_claims": len(rows), "old": old, "best": best, "grid": grid, "rows": rows}
    # javob darajalari: oldin / keyin
    lv = {}
    for x in items:
        if x["kind"] in ("ru_real", "ru_trans", "uz_real"):
            rs = [r for r in rows if r["item"] == x["id"] and r["kind"] == x["kind"]]
            lv[f"{x['kind']}:{x['id']}"] = {"before": level_of(rs, old), "after": level_of(rs, best)}
    out["levels"] = lv
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    def dist(kind, key):
        from collections import Counter
        c = Counter(v[key] for k, v in lv.items() if k.startswith(kind + ":"))
        return {k: c.get(k, 0) for k in ("high", "medium", "low")}
    for kinds, name in ((("ru_real", "ru_trans"), "ruscha toʻgʻri"), (("false_ru",), "ruscha notoʻgʻri"),
                        (("cross_ru",), "ruscha, boshqa manba"), (("uz_real",), "oʻzbekcha toʻgʻri"),
                        (("false_uz",), "oʻzbekcha notoʻgʻri"), (("cross_uz",), "oʻzbekcha, boshqa manba")):
        a, n = rate(rows, old, kinds)
        b, _ = rate(rows, best, kinds)
        print(f"{name:24} tasdiqlangan: oldin {a}/{n} -> keyin {b}/{n}")
    print("eng yaxshi:", {k: best[k] for k in ("ok", "num", "ctx", "tpr", "fpr", "j")})
    for r in rows:
        if r["kind"] in ("false_ru", "false_uz"):
            print(f"  {r['kind']:8} {'OTDI ' if supported(r, best if r['lang'] == 'ru' else old) else 'rad  '}"
                  f"cos {r['cos']:.3f} ctx {r['cos_ctx']:.3f} lex {r['lex']} nums {r['nums']} miss {r['missing']} | {r['claim'][:70]}")
    for ok_ in (0.58, 0.60, 0.62):
        for num in (0.52, 0.56, 0.60):
            g = next((g for g in grid if g["ok"] == ok_ and g["num"] == num and g["ctx"]), None)
            if g:
                f, nf = rate(rows, g, ("false_ru",))
                print(f"  ok {ok_} num {num}: toʻgʻri {g['tp']}/{g['npos']}, notoʻgʻri {f}/{nf}, boshqa manba "
                      f"{rate(rows, g, ('cross_ru',))[0]}")
    for kind in ("ru_real", "ru_trans", "uz_real"):
        print(f"daraja {kind:9} oldin {dist(kind, 'before')} -> keyin {dist(kind, 'after')}")
    print("->", OUT)


if __name__ == "__main__":
    main()
