"""4-bosqich unit testlari (LLM'siz, tez): o'zbek stemmeri, stopwordlar, translit va so'z tiklash, ruscha sonlar.

    .venv/bin/python scripts/test_stage4.py            # ~1 s (indeks va model yuklanmaydi)
    .venv/bin/python scripts/test_stage4.py --index    # + yangi BM25 indeksi (data/index/bm25_new) bilan tekshiruv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag.stem import fold, stem, tokenize  # noqa: E402
from lexrag.translit import cyr_to_lat, lat_to_cyr, repair_latin, repair_word  # noqa: E402

results: list[tuple[bool, str]] = []


def ok(cond: bool, name: str, info: str = ""):
    results.append((cond, name))
    print(f"{'OK  ' if cond else 'XATO'} {name}" + (f" — {info}" if info and not cond else ""), flush=True)


def same_stem(words: str, name: str):
    ws = words.split()
    st = {stem(w) for w in ws}
    ok(len(st) == 1, f"stem: {name}", " ".join(f"{w}>{stem(w)}" for w in ws))


def phase_stem():
    same_stem("taʼtil taʼtilni taʼtilining taʼtillari taʼtilga taʼtilda", "kelishik va egalik (taʼtil)")
    same_stem("tatil ta'til taʼtil", "apostrof shakllari bir xil token")
    same_stem("oʻgʻirlik o'g'irlik ogirlik", "apostrofsiz yozuv")
    same_stem("ish ishni ishga ishdan ishi", "qisqa o'zak (ish)")
    same_stem("xodim xodimga xodimlari xodimi xodimning", "KEEP: xodim (-im egalik emas)")
    same_stem("taʼlim taʼlimi taʼlimga", "KEEP: taʼlim ('-mi' yuklama emas)")
    same_stem("qonun qonuni qonunni qonunga", "n bilan tugaydigan o'zak (qonun|i, -ni emas)")
    same_stem("shaxs shaxsi shaxsga", "s bilan tugaydigan o'zak (shaxs|i)")
    same_stem("beriladi berilishi berilgan", "fe'l: majhul nisbat + -adi / -ishi / -gan")
    same_stem("toʻlanadi toʻlash toʻlangan", "fe'l: toʻla-n-adi")
    same_stem("boʻshatilganda boʻshatish boʻshatmoqchi", "fe'l: -ilganda / -ish / -moqchi")
    same_stem("bola bolalar bolalarning bolani", "ko'plik + kelishik")
    ok(stem("mumkinmi") == stem("mumkin"), "stem: -mi yuklama")
    ok(stem("ijarachi") == "ijarachi" and stem("beruvchi") == "beruvchi", "stem: -chi yasovchi saqlanadi (-i egalik emas)")
    ok(stem("qancha") == "qancha" and stem("necha") == "necha", "stem: qisqa so'zdan -cha olinmaydi")
    ok(stem("1-modda") == "1-modda" or stem("12") == "12", "stem: raqam o'zgarmaydi")
    ok(fold("Oʻzbekiston") == "ozbekiston", "fold: kichik harf, apostrofsiz")
    t = tokenize("Ishchiga har yili kamida necha kun dam olish taʼtili berilishi kerak?")
    ok("necha" not in t and "kerak" not in t and "har" not in t, "stopword: savol so'zlari tashlanadi", str(t))
    ok("tatil" in t and "kun" in t and "ishchi" in t, "tokenize: mazmunli so'zlar qoladi", str(t))
    ok("ber" not in t, "stopword: yengil fe'l 'beriladi' (ber-) tashlanadi", str(t))
    m = stem("modda")
    ok(stem("moddasi") == m and stem("moddada") == m, "stem: modda / moddasi / moddada bir xil")
    ok(m in tokenize("modda") and m not in tokenize("modda", stop="legal"), "stopword: 'legal' ro'yxati faqat tanlansa")
    ok(tokenize("Qancha?", stop="none") == ["qancha"], "stop=none: hech narsa tashlanmaydi")


def phase_translit():
    cases = {
        "Ер": "Yer", "иерархия": "iyerarxiya", "Ўзбекистон": "Oʻzbekiston", "маъмурий": "maʼmuriy",
        "компенсация": "kompensatsiya", "цех": "sex", "Юрист": "Yurist", "ёзма": "yozma", "яшаш": "yashash",
        "ҳуқуқ": "huquq", "ғалаба": "gʻalaba", "қўшимча": "qoʻshimcha", "энди": "endi", "поезд": "poyezd",
        "съезд": "sʼyezd", "ЎЗБЕКИСТОН": "OʻZBEKISTON",
    }
    bad = {c: (cyr_to_lat(c), l) for c, l in cases.items() if cyr_to_lat(c) != l}
    ok(not bad, f"cyr_to_lat: {len(cases)} ta so'z (е/ye, ц, ё, ю, я, ъ, ў, қ, ғ, ҳ, katta harf)", str(bad))
    back = "Xodimga yillik taʼtil 21 kun beriladi [1]."
    ok(cyr_to_lat(lat_to_cyr(back)) == back, "lat_to_cyr -> cyr_to_lat aylanma", cyr_to_lat(lat_to_cyr(back)))
    voc = {"toliq": ["toʻliq", 900, 800], "tolanadimi": ["toʻlanadimi", 12, 12], "qilsam": ["qilsam", 30, 30],
           "hozir": ["hozir", 400, 400], "boladimi": ["boʻladimi", 50, 50], "kun": ["kun", 9000, 9000],
           "mahalla": ["mahalla", 700, 700], "kancha": None}
    voc = {k: v for k, v in voc.items() if v}
    ok(repair_word("tulik", voc, letters=True) == "toʻliq", "repair: rus klaviaturasi у->ў, к->қ (tulik -> toʻliq)",
       repair_word("tulik", voc, letters=True))
    ok(repair_word("xozir", voc, letters=True) == "hozir", "repair: х->ҳ (xozir -> hozir)")
    ok(repair_word("Maxalla", voc, letters=True) == "Mahalla", "repair: bosh harf saqlanadi")
    ok(repair_word("boladimi", voc) == "boʻladimi", "repair: lotin apostrofsiz (boladimi -> boʻladimi)")
    ok(repair_word("tulik", voc, letters=False) == "tulik", "repair: lotin savolda harf almashtirilmaydi")
    ok(repair_word("kun", voc, letters=True) == "kun", "repair: korpusda bor so'z o'zgarmaydi")
    ok(repair_word("noma'lumso'z", voc, letters=True) == "noma'lumso'z", "repair: topilmasa o'zgarmaydi")
    ok(repair_latin("Pensiyasi tulik tulanadimi?", voc, letters=True) == "Pensiyasi toʻliq toʻlanadimi?",
       "repair_latin: gap ichida, tinish belgilari saqlanadi")


def phase_ru_numbers():
    from lexrag.trust import _ru_num_words
    cases = {"не менее чем на пятнадцать дней": {"15"}, "двадцать пять процентов": {"25"},
             "семьдесят календарных дней": {"70"}, "до трех суток": {"3"}, "пятидесяти процентов": {"50"},
             "сто двадцать": {"120"}, "две тысячи": {"2000"}}
    bad = {t: _ru_num_words(t, claim=True) for t, exp in cases.items() if _ru_num_words(t, claim=True) != exp}
    ok(not bad, f"trust: ruscha son so'zlari ({len(cases)} ta)", str(bad))
    ok(_ru_num_words("одно и то же лицо", claim=True) == set(), "trust: yolg'iz 'одно' raqam emas")
    ok(_ru_num_words("стоимость товара", claim=True) == set(), "trust: 'стоимость' -> 'сто' emas")


def phase_index():
    import json
    from lexrag import config, retrieval as R
    d = config.INDEX_DIR / "bm25_new"
    ids = json.loads((d / "ids.json").read_text(encoding="utf-8"))
    ok(ids.get("tokenizer", {}).get("kind") == "stem", "bm25_new: tokenizator stem", str(ids.get("tokenizer")))
    ok((d / "vocab.json").exists(), "bm25_new: vocab.json bor")
    R.use_bm25_dir(d)
    ok(R.tokenize("Taʼtilni necha kun?") == ["tatil", "kun"], "retrieval.tokenize: indeks sozlamasi + stopword",
       str(R.tokenize("Taʼtilni necha kun?")))
    hits = R.bm25_search("yillik mehnat taʼtili", 5, True, True)
    ok(len(hits) == 5, "bm25_search: natija bor")
    R.use_bm25_dir(config.INDEX_DIR / "bm25")
    ok(R._bm25_cfg().get("kind") in ("trunc7", "stem"), "eski indeks: tokenizator aniqlandi (7 harf)",
       str(R._bm25_cfg()))


def phase_trust_ru():
    """Haqiqiy ruscha LLM javoblari (eval/answers_ru.json, qo'lda tekshirilgan - to'g'ri) va o'zgartirilgan sonlar."""
    import json
    from collections import Counter
    from lexrag import trust
    d = json.loads((ROOT / "eval" / "answers_ru.json").read_text(encoding="utf-8"))
    items = [i for i in d["items"] if i["status"] == "ok"]
    lv = Counter(trust.check(i["answer"], i["chunk_ids"], "ru")["level"] for i in items)
    ok(lv.get("low", 0) == 0, f"trust ru: {len(items)} ta toʻgʻri ruscha javobda 'Past' yoʻq", str(dict(lv)))
    a04 = next(i for i in items if i["id"] == "a04")
    bad = "Работодатель вправе удерживать до девяноста процентов зарплаты при каждой выплате [1]."
    r = trust.check(bad, a04["chunk_ids"], "ru")
    ok(r["level"] == "low" and any("90 raqami" in x for x in r["claims"][0]["reasons"]),
       "trust ru: soʻz bilan yozilgan notoʻgʻri son (девяноста = 90) aniqlandi", str(r["claims"][0]["reasons"]))
    good = "Общая сумма удержаний не может превышать пятидесяти процентов начисленной заработной платы [1]."
    ok(trust.check(good, a04["chunk_ids"], "ru")["level"] == "high", "trust ru: toʻgʻri son (пятидесяти = 50) -> Yuqori")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="store_true", help="BM25 indeksi va ishonch tekshiruvi (bge-m3 yuklanadi)")
    a = ap.parse_args()
    phase_stem()
    phase_translit()
    phase_ru_numbers()
    if a.index:
        phase_index()
        phase_trust_ru()
    bad = [n for c, n in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} o'tdi")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
