"""Baholash hisoboti: eval/results.md va report.md "6. Baholash" bo'limi (results.json, sweep.json, baseline_v2.json,
trust_calibration.json dan). Asosiy raqamlar - TEST qismi (sozlashda ishlatilmagan), DEV - qavsda / alohida."""
from __future__ import annotations

import json
from pathlib import Path

from . import config

EVAL_DIR = config.ROOT / "eval"
MODE_NAMES = {"dense": "Dense (bge-m3)", "bm25": "BM25", "hybrid": "Gibrid (RRF)", "hybrid_plan": "Gibrid + bo'lish"}
LANG_NAMES = {"uz": "lotin", "uz_cyr": "kirill", "ru": "rus"}
SPLITS = ("test", "dev")


def _p(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _d(a, b, pct=True) -> str:
    """oldin -> keyin farqi."""
    if a is None or b is None:
        return "—"
    d = b - a
    return (f"{d * 100:+.1f} p.p." if pct else f"{d:+.3f}") if abs(d) > 1e-9 else "0"


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _summary_table(S: dict, modes) -> list[str]:
    L = ["| Rejim | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | o'rtacha vaqt |", "|---|---|---|---|---|---|---|---|"]
    for mo in modes:
        s = S[mo]
        L.append(f"| {MODE_NAMES[mo]} | {_p(s['recall@1'])} | {_p(s['recall@3'])} | {_p(s['recall@5'])} | {_p(s['recall@10'])} "
                 f"| {s['mrr@10']:.3f} | {s['ndcg@10']:.3f} | {s['avg_ms']:.0f} ms |")
    return L


def compare_rows(base: dict, r: dict, split: str) -> list[tuple[str, float | None, float | None, bool]]:
    """(nom, oldin, keyin, foizmi) - oldin/keyin jadvali uchun (veb-sahifa ham shu mantiqni takrorlaydi)."""
    B, A = base["by_split"][split], r["by_split"][split]
    rows = []
    for mo, nm in (("hybrid", "Gibrid"), ("bm25", "BM25 yolgʻiz"), ("dense", "Dense"), ("hybrid_plan", "Gibrid + boʻlish")):
        if mo in A["summary"] and mo in B["summary"]:
            rows.append((f"{nm} R@5", B["summary"][mo]["recall@5"], A["summary"][mo]["recall@5"], True))
            rows.append((f"{nm} R@1", B["summary"][mo]["recall@1"], A["summary"][mo]["recall@1"], True))
            rows.append((f"{nm} MRR@10", B["summary"][mo]["mrr@10"], A["summary"][mo]["mrr@10"], False))
    for lg in ("uz", "uz_cyr", "ru"):
        b = B["slices"]["lang"].get(lg, {}).get("hybrid")
        a = A["slices"]["lang"].get(lg, {}).get("hybrid")
        if a and b:
            rows.append((f"Gibrid R@5, {LANG_NAMES[lg]}", b["recall@5"], a["recall@5"], True))
        b = B["slices"]["lang"].get(lg, {}).get("bm25")
        a = A["slices"]["lang"].get(lg, {}).get("bm25")
        if a and b and lg != "ru":
            rows.append((f"BM25 R@5, {LANG_NAMES[lg]}", b["recall@5"], a["recall@5"], True))
    return rows


def markdown(r: dict, sw: dict | None) -> str:
    m = r["meta"]
    p = m["params"]
    modes = m["modes"]
    base = _load(EVAL_DIR / "baseline_v2.json")
    bs = r.get("by_split") or {}
    L = ["# Qidiruv sifatini baholash", "",
         f"Yaratilgan: {m['created']} · commit `{m['commit']}`{' (lexrag/ da commit qilinmagan oʻzgarish bor)' if m['dirty'] else ''}"
         f" · {m['elapsed_s']} s · BM25 indeksi: `{p.get('bm25_dir', '—')}`", "",
         f"Savollar: {m['n_questions']} ta ({m['n_answerable']} tasining javobi bazada bor, {m['n_none']} tasi bazada yoʻq). "
         "Til: " + ", ".join(f"{LANG_NAMES.get(k, k)} {v}" for k, v in m["counts"]["lang"].items()) + ". "
         + (f"Qismlar: DEV {bs['dev']['n_questions']} (sozlash shu yerda), TEST {bs['test']['n_questions']} (yakuniy raqamlar). "
            if "dev" in bs and "test" in bs else "")
         + f"Sozlamalar: W_DENSE={p['W_DENSE']}, W_BM25={p['W_BM25']}, RRF_K={p['RRF_K']}, har usuldan {p['N_EACH']} ta nomzod, "
           f"NO_ANSWER_COS={p['NO_ANSWER_COS']}, BM25 tokenizatori {p.get('tokenizer', '—')}, soʻrov stopwordlari "
           f"{p.get('query_stop', '—')}, ruscha BM25 {p.get('ru_bm25', '—')}, soʻz tiklash {p.get('repair', '—')}; "
           "filtr: faqat amaldagi, oʻzgartirish qonunlarisiz. LLM chaqirilmagan.", ""]
    for s in SPLITS:
        if s not in bs:
            continue
        B = bs[s]
        L += [f"## Asosiy natija — {s.upper()} ({B['n_answerable']} javobli, {B['n_none']} yoʻq)", ""] + _summary_table(B["summary"], modes)
        L.append("")
    if base and "by_split" in base and bs:
        L += ["## Oldin / keyin (baseline_v2 — 3-bosqich kodi shu toʻplamda → hozir)", "",
              "| Koʻrsatkich | TEST oldin | TEST keyin | farq | DEV oldin | DEV keyin | farq |", "|---|---|---|---|---|---|---|"]
        rt, rd = compare_rows(base, r, "test"), compare_rows(base, r, "dev")
        dd = {x[0]: x for x in rd}
        for name, b, a, pc in rt:
            f = _p if pc else (lambda v: f"{v:.3f}")
            d = dd.get(name)
            L.append(f"| {name} | {f(b)} | {f(a)} | {_d(b, a, pc)} | " +
                     (f"{f(d[1])} | {f(d[2])} | {_d(d[1], d[2], pc)} |" if d else "— | — | — |"))
        for s in SPLITS:
            rb, ra = base["by_split"][s]["rejection"].get("hybrid"), bs[s]["rejection"].get("hybrid")
            if rb and ra:
                L.append(f"| Rad etish ({s.upper()}): toʻgʻri / xato | {rb['correct_reject']}/{rb['n_none']} · {rb['false_reject']}/{rb['n_answerable']} "
                         f"| {ra['correct_reject']}/{ra['n_none']} · {ra['false_reject']}/{ra['n_answerable']} | | | | |")
        L.append("")
    L += ["## \"Bazada yoʻq\" savollarni rad etish", "",
          f"Chegara NO_ANSWER_COS = {p['NO_ANSWER_COS']} (LLM'ga beriladigan {p['K_CONTEXT']} ta manbaning eng yuqori cosine'i shundan past boʻlsa — \"topilmadi\").", "",
          "| Rejim | qism | toʻgʻri rad etildi | notoʻgʻri rad etildi (javobi bor savol) | aniqlik |", "|---|---|---|---|---|"]
    for mo in modes:
        for s in SPLITS:
            x = bs.get(s, {}).get("rejection", {}).get(mo)
            if x:
                L.append(f"| {MODE_NAMES[mo]} | {s.upper()} | {x['correct_reject']}/{x['n_none']} | {x['false_reject']}/{x['n_answerable']} | {_p(x['accuracy'])} |")
    for f, title in (("lang", "Til / yozuv"), ("category", "Kategoriya"), ("difficulty", "Qiyinlik")):
        L += ["", f"## {title} boʻyicha recall@5 (TEST | DEV)", "",
              f"| {title} | n (T/D) | " + " | ".join(MODE_NAMES[mo] for mo in modes) + " |", "|---|---|" + "---|" * len(modes)]
        keys = list(dict.fromkeys(list(bs.get("test", {}).get("slices", {}).get(f, {})) + list(bs.get("dev", {}).get("slices", {}).get(f, {}))))
        for v in keys:
            t = bs.get("test", {}).get("slices", {}).get(f, {}).get(v)
            d = bs.get("dev", {}).get("slices", {}).get(f, {}).get(v)
            n = f"{next(iter(t.values()))['n'] if t else 0}/{next(iter(d.values()))['n'] if d else 0}"
            cells = [f"{_p(t[mo]['recall@5']) if t else '—'} \\| {_p(d[mo]['recall@5']) if d else '—'}" for mo in modes]
            L.append(f"| {LANG_NAMES.get(v, v) if f == 'lang' else v} | {n} | " + " | ".join(cells) + " |")
    if sw:
        w = sw["w_bm25"]
        g = w.get("grid_by_split", {})
        L += ["", f"## Sweep: W_BM25 (gibrid) — tanlash {sw.get('selected_on', 'dev').upper()} boʻyicha", "",
              "| W_BM25 | DEV R@1 | DEV R@5 | DEV MRR@10 | TEST R@5 | TEST MRR@10 |", "|---|---|---|---|---|---|"]
        for i, row in enumerate(w["grid"]):
            t = g.get("test", [None] * len(w["grid"]))[i]
            mark = " (joriy)" if row["w_bm25"] == w["current"] else ""
            L.append(f"| {row['w_bm25']}{mark} | {_p(row['recall@1'])} | {_p(row['recall@5'])} | {row['mrr@10']:.3f} | "
                     f"{_p(t['recall@5']) if t else '—'} | {t['mrr@10']:.3f} |" if t else "— | — |")
        L.append(f"\nEng yaxshi (DEV, recall@5, teng boʻlsa MRR@10): W_BM25 = {w['best']['w_bm25']}. {w['note']}")
        c = sw["no_answer_cos"]
        cg = c.get("grid_by_split", {})
        L += ["", "## Sweep: NO_ANSWER_COS (tanlash DEV boʻyicha: xato rad ≤ 1% sharti bilan eng koʻp toʻgʻri rad)", "",
              "| chegara | DEV toʻgʻri rad | DEV xato rad | TEST toʻgʻri rad | TEST xato rad |", "|---|---|---|---|---|"]
        for i, row in enumerate(c["grid"]):
            if round(row["threshold"] * 100) % 4 == 2 or abs(row["threshold"] - c["current"]) < 1e-9:
                t = cg.get("test", [None] * len(c["grid"]))[i]
                mark = " (joriy)" if abs(row["threshold"] - c["current"]) < 1e-9 else ""
                L.append(f"| {row['threshold']:.2f}{mark} | {row['correct_reject']}/{row['n_none']} | {row['false_reject']}/{row['n_answerable']} | "
                         + (f"{t['correct_reject']}/{t['n_none']} | {t['false_reject']}/{t['n_answerable']} |" if t else "— | — |"))
        L.append(f"\nEng yaxshi (DEV): {c['best']['threshold']}. ")
        for s in SPLITS:
            info = c.get("by_split", {}).get(s)
            if info:
                a = info["answerable_cos"]
                L.append(f"{s.upper()}: javobi bor savollarda eng yaqin cosine min {a['min']}, 10-persentil {a['p10']}, "
                         f"mediana {a['median']}; bazada yoʻq savollarda {', '.join(str(x) for x in info['none_cos'])}. "
                         + ("Ikki guruh toʻliq ajraladi." if info["separable"] else "Ikki guruh toʻliq ajralmaydi."))
    for s in SPLITS:
        L += ["", f"## Xatolar — {s.upper()} (gibrid: gold modda top-5 da yoʻq)", "",
              "| id | til | savol | gold | gibrid oʻrni | dense oʻrni | BM25 oʻrni |", "|---|---|---|---|---|---|---|"]
        for q in r["questions"]:
            if q.get("split", "dev") != s or not q["answerable"] or "hybrid" not in q["modes"]:
                continue
            rk = q["modes"]["hybrid"]["metrics"]["rank"]
            if rk is None or rk > 5:
                gd = "; ".join(f"{x['doc']} {x['article']}-m." for x in q["gold"])
                L.append(f"| {q['id']} | {LANG_NAMES.get(q['lang'], q['lang'])} | {q['question']} | {gd} | {rk or '>10'} "
                         f"| {q['gold_rank_dense'] or '>40'} | {q['gold_rank_bm25'] or '>40'} |")
    if m.get("lang_detect_errors"):
        L += ["", "Til aniqlash xatolari (yorliq ≠ ilova aniqlagan): " +
              ", ".join(f"{e['id']} ({e['lang']}→{e['detected']})" for e in m["lang_detect_errors"])]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- report.md
def _get(r, split, mode, key, slice_=None, val=None):
    try:
        B = r["by_split"][split]
        return B["slices"][slice_][val][mode][key] if slice_ else B["summary"][mode][key]
    except (KeyError, TypeError):
        return None


def _ba(base, r, mode, key, slice_=None, val=None, pct=True) -> str:
    """'TEST oldin → keyin (DEV oldin → keyin)'."""
    f = _p if pct else (lambda v: "—" if v is None else f"{v:.3f}")
    t0, t1 = _get(base, "test", mode, key, slice_, val), _get(r, "test", mode, key, slice_, val)
    d0, d1 = _get(base, "dev", mode, key, slice_, val), _get(r, "dev", mode, key, slice_, val)
    return f"{f(t0)} → **{f(t1)}** (DEV {f(d0)} → {f(d1)})"


def report_section() -> str:
    r, sw = _load(EVAL_DIR / "results.json"), _load(EVAL_DIR / "sweep.json")
    base, st3 = _load(EVAL_DIR / "baseline_v2.json"), _load(EVAL_DIR / "baseline_stage3.json")
    cal, tun = _load(EVAL_DIR / "trust_calibration.json"), _load(EVAL_DIR / "tuning_stage4.json")
    if not r or "by_split" not in r:
        return ""
    m, p = r["meta"], r["meta"]["params"]
    bs = r["by_split"]
    lang = m["counts"]["lang"]
    n_none_lang: dict = {}
    for q in r["questions"]:
        if not q["answerable"]:
            n_none_lang[q["lang"]] = n_none_lang.get(q["lang"], 0) + 1
    L = ["## 6. Baholash (qidiruv sifati)", "",
         f"To'plam: `eval/questions.jsonl`, **{m['n_questions']} savol** — {m['n_answerable']} tasi gold modda bilan, "
         f"{m['n_none']} tasi ataylab bazada yo'q (chet el qonunlari, umumiy savollar, bazada yo'q soha). Yozuv/til: "
         + ", ".join(f"{LANG_NAMES[k]} {lang.get(k, 0) - n_none_lang.get(k, 0)}" for k in ("uz", "uz_cyr", "ru"))
         + f" + {m['n_none']} \"yo'q\"; {len(m['counts']['category'])} kategoriya; qiyinlik: "
         + ", ".join(f"{k} {v}" for k, v in m["counts"]["difficulty"].items()) + ". "
         f"Ikki qism: **DEV {bs['dev']['n_questions']}** (barcha sozlash — sweep, chegaralar, stemmer — faqat shu yerda) va "
         f"**TEST {bs['test']['n_questions']}** (yakuniy raqamlar; sozlashda qaralmagan), tasodifiy, seed bilan, kategoriya va "
         "til bo'yicha muvozanatli. 3-bosqichdagi 50 savol o'zgarmagan; yangi 120 savolni Claude (Anthropic) yordamchi "
         "agentlari moddani `data/chunks.jsonl` dan o'qib, oddiy odam tilida parafraza qilib yozdi (qidiruv tizimi va Gemini "
         "ishlatilmadi); har gold modda bazada borligi va moddadan olingan iqtibos (`evidence`) avtomatik tekshirildi. "
         "Kirill savollarning bir qismi ataylab rus klaviaturasida (у/к/х o'rniga ў/қ/ҳ), lotinning bir qismi apostrofsiz "
         "yozilgan — real foydalanuvchilar kabi. LLM'siz. Metodika: `eval/README.md`, to'liq jadvallar: `eval/results.md`.", "",
         f"### Hozirgi natija — TEST ({bs['test']['n_answerable']} javobli savol)", ""] + _summary_table(bs["test"]["summary"], m["modes"])
    L += ["", f"DEV ({bs['dev']['n_answerable']} javobli): " + ", ".join(
        f"{MODE_NAMES[mo]} R@5 {_p(bs['dev']['summary'][mo]['recall@5'])} / MRR {bs['dev']['summary'][mo]['mrr@10']:.3f}" for mo in m["modes"]) + "."]
    if not base:
        return "\n".join(L) + "\n"
    rt, rd = bs["test"]["rejection"]["hybrid"], bs["dev"]["rejection"]["hybrid"]
    L += ["", "### 4-bosqich: zaif joylarni tuzatish", "",
          "\"Oldin\" — 3-bosqich kodi aynan shu 170 savolda (`eval/baseline_v2.json`), \"keyin\" — hozirgi kod. Har qatorda "
          "TEST, qavsda DEV. TEST'da 80 ta javobli savol: bitta savol ≈ 1.25 foiz punkt, shuning uchun ~3 punktdan kichik farq "
          "shovqin chegarasida.", "",
          "| Zaif joy | Sabab (DEV'da topilgan) | Nima qilindi | Natija: TEST oldin → keyin (DEV) |", "|---|---|---|---|"]
    st3_cyr = st3 and st3["slices"]["lang"].get("uz_cyr", {}).get("hybrid", {}).get("recall@5")
    st3_lat = st3 and st3["slices"]["lang"].get("uz", {}).get("hybrid", {}).get("recall@5")
    L.append(
        "| Kirill savollar (3-bosqich: 8 savolda gibrid R@5 " + _p(st3_cyr) + ", lotin " + _p(st3_lat) + ") | "
        "Kengaytirilgan to'plamda kirill lotindan yomon emas (oldin: TEST kirill " + _p(_get(base, "test", "hybrid", "recall@5", "lang", "uz_cyr"))
        + ", lotin " + _p(_get(base, "test", "hybrid", "recall@5", "lang", "uz")) + ") — eski farq kichik namunaning shovqini edi. "
        "Translit to'g'ri ishlaydi (е/ye, ц, ё, ю, я, ъ). Aniq sabab: rus klaviaturasida yozilgan savol (\"тулик туланадими\" → "
        "`tulik tulanadimi`, aslida `toʻliq toʻlanadimi`) — bunday so'z korpusda yo'q, BM25 topmaydi. Asl kirill matnni dense'ga "
        "berish yomonroq (DEV kirill R@5 85.6% → 72.2%) | "
        "Korpus lug'ati bo'yicha so'z tiklash (`translit.repair_latin`: у→ў, к→қ, х→ҳ, г→ғ variantlari va apostrofsiz shakl) — "
        "faqat BM25 so'roviga (dense'ga berish DEV'da bitta savolni 2 → 6-o'ringa tushirdi) | "
        "Gibrid R@5 kirill: " + _ba(base, r, "hybrid", "recall@5", "lang", "uz_cyr") + "; BM25 R@5 kirill: "
        + _ba(base, r, "bm25", "recall@5", "lang", "uz_cyr") + " |")
    L.append(
        "| BM25 kuchsiz (TEST R@5 " + _p(_get(base, "test", "bm25", "recall@5")) + ") | So'z 7 harfgacha kesilardi: \"taʼtilining\" va "
        "\"taʼtil\" mos kelmaydi, qisqa so'zlar umuman qisqarmaydi; \"uchun\", \"qanday\", \"kerak\" kabi so'zlar ball oladi | "
        "`lexrag/stem.py`: qoidaga asoslangan suffix stripper (kelishik, egalik, ko'plik, yuklama, fe'l -adi/-gan/-ish + majhul "
        "nisbat), apostrof normalizatsiyasi, minimal o'zak, istisnolar (xodim, taʼlim, qonun|i — korpusdan); so'rov "
        "stopwordlari. \"modda/qonun\"ni tashlash DEV'da ta'sir qilmadi — kiritilmadi. Indeks `data/index/bm25_new` | "
        "BM25 R@5: " + _ba(base, r, "bm25", "recall@5") + "; BM25 MRR: " + _ba(base, r, "bm25", "mrr@10", pct=False) + " |")
    L.append(
        "| Gibrid (asosiy rejim) | BM25 shovqini RRF'da to'g'ri moddani pastga surardi | Yangi BM25 + W_BM25 DEV'da qayta sweep "
        "(0.05…2.0): eng yaxshisi yana **0.05** — o'zgarmadi; stemmer bilan katta og'irlik kamroq zarar qiladi "
        "(DEV, W=0.6: R@5 67.7% → 74.9%) | "
        "R@5: " + _ba(base, r, "hybrid", "recall@5") + "; R@1: " + _ba(base, r, "hybrid", "recall@1")
        + "; MRR: " + _ba(base, r, "hybrid", "mrr@10", pct=False) + " |")
    L.append(
        "| Ruscha savol BM25'da | Baza o'zbekcha; lotinlashtirilgan ruscha so'zlar (`skolko dney`) BM25'ga shovqin | "
        "Ruscha savol BM25'ga yuborilmaydi (`RU_BM25=off`; DEV'da lug'atli variantdan teng yoki biroz yaxshi) | "
        "Gibrid R@5 rus: " + _ba(base, r, "hybrid", "recall@5", "lang", "ru") + " — o'zgarmadi, ruscha savollarni dense (bge-m3) topadi |")
    if cal:
        rows = cal["rows"]
        best, old = cal["best"], cal["old"]

        def cnt(kinds, prm):
            rs = [x for x in rows if x["kind"] in kinds]
            return sum(_sup(x, prm) for x in rs), len(rs)
        a0, n0 = cnt(("ru_real", "ru_trans"), old)
        a1, _ = cnt(("ru_real", "ru_trans"), best)
        f0, nf = cnt(("false_ru",), old)
        f1, _ = cnt(("false_ru",), best)
        u0, nu = cnt(("false_uz",), old)
        lv = cal["levels"]

        def dist(kind, key):
            c = {"high": 0, "medium": 0, "low": 0}
            for k, v in lv.items():
                if k.startswith(kind + ":") and v[key]:
                    c[v[key]] += 1
            return f"Yuqori {c['high']} / O'rta {c['medium']} / Past {c['low']}"
        L.append(
            "| Ruscha javobda ishonch belgisi | Manba o'zbekcha: bge-m3 tillararo o'xshashligi pastroq (to'g'ri ruscha da'volarda "
            "0.49–0.78), leksik moslik yo'q; chegara (0.64) o'zbekchadagidek edi; ruscha son so'zlari tanilmasdi | "
            f"Alohida chegaralar (COS_OK_RU {old['ok']} → {best['ok']}; sonli da'vo, sonlar manbada bo'lsa {best['num']}), ro'yxat bandi "
            "kirish qatori bilan solishtiriladi, ruscha son so'zlari (\"пятнадцать\" = 15) raqam tekshiruviga qo'shildi. "
            "Kalibrlash: 7 ta haqiqiy ruscha LLM javobi + 4 ta qo'lda tarjima + ataylab noto'g'ri da'volar | "
            f"Haqiqiy ruscha javoblar (7): {dist('ru_real', 'before')} → **{dist('ru_real', 'after')}**; to'g'ri ruscha da'volar "
            f"tasdiqlandi {a0}/{n0} → **{a1}/{n0}**; yolg'on ruscha da'volar o'tib ketdi {f0}/{nf} → {f1}/{nf} (o'zbekcha qoidalar "
            f"o'sha da'volarning o'zbekcha variantidan {u0}/{nu} o'tkazadi — endi teng qattiqlik); o'zbekcha: o'zgarmadi "
            f"({dist('uz_real', 'before')}) |")
    L.append(
        f"| \"Bazada yo'q\" savollar | Sweep'ning eski mezoni (balanslangan aniqlik) DEV'da 0.62 ni tanlardi — 4 ta \"yo'q\" savolga "
        "katta og'irlik berib, javobi bor savollarning 32% ini rad etardi | Mezon: xato rad ≤ 1% sharti bilan eng ko'p to'g'ri rad; "
        f"DEV'da 0.46–0.52 teng → NO_ANSWER_COS **{p['NO_ANSWER_COS']}** o'zgarmadi | TEST: {rt['correct_reject']}/{rt['n_none']} to'g'ri rad, "
        f"{rt['false_reject']}/{rt['n_answerable']} xato (DEV {rd['correct_reject']}/{rd['n_none']}, {rd['false_reject']}/{rd['n_answerable']}) |")
    # TEST'dagi gibrid R@5 o'zgargan savollar
    if base:
        bq = {q["id"]: q for q in base["questions"]}
        up, dn, top = [], [], 0
        for q in r["questions"]:
            if q["split"] != "test" or not q["answerable"]:
                continue
            a, b = bq[q["id"]]["modes"]["hybrid"]["metrics"], q["modes"]["hybrid"]["metrics"]
            if b["recall@5"] > a["recall@5"]:
                up.append(f"{q['id']} ({a['rank'] or '>10'}→{b['rank']})")
            elif b["recall@5"] < a["recall@5"]:
                dn.append(f"{q['id']} ({a['rank']}→{b['rank'] or '>10'})")
            if (b["rank"] or 99) < (a["rank"] or 99):
                top += 1
        L += ["", f"TEST'da gibrid R@5 bo'yicha {len(up)} ta savol yaxshilandi ({', '.join(up) or '—'}), {len(dn)} tasi yomonlashdi "
                  f"({', '.join(dn) or '—'}; 5-o'rin chegarasidagi siljishlar); {top} ta savolda gold modda yuqoriroq o'ringa chiqdi — "
                  "shuning uchun R@1 va MRR o'sdi, R@5 deyarli o'zgarmadi."]
    if tun:
        L += ["", "DEV'dagi sozlash variantlari (`scripts/tune_stage4.py` → `eval/tuning_stage4.json`): kirill uchun 5 ta, BM25 "
                  "tokenizatori/stopwordlar uchun 7 ta, ruscha BM25 uchun 3 ta variant va W_BM25 sweep."]
    L += ["", "Cheklovlar:", "",
          "* Savollarni bitta model oilasi (Claude) yozgan — uslub bir xilligi bo'lishi mumkin; haqiqiy foydalanuvchi savollari "
          "logi bilan tekshirish kerak.",
          "* TEST kichik (80 javobli savol): 1 savol ≈ 1.25 p.p. Gibrid R@5 dagi o'zgarish shovqin chegarasida; ishonchli "
          "o'sish — BM25 (≈ +11 p.p.), gibrid R@1 va MRR.",
          f"* \"Bazada yo'q\" savollar {m['n_none']} ta. Chet el qonunlari haqidagi savollar (Rossiya ta'tili, AQSh guvohnomasi, "
          "Qozog'iston pensiyasi) O'zbekiston moddalariga ma'no jihatdan yaqin (cosine 0.61–0.69) — ularni cosine chegarasi bilan "
          "rad etib bo'lmaydi; buni LLM \"manbada yo'q\" deb aytishi kerak (system prompt 4-qoida).",
          "* Ishonch kalibrlashi kichik namunada (37 to'g'ri va 17 yolg'on ruscha da'vo) va o'sha namunada tanlangan; mazmunan "
          "noto'g'ri, lekin mavzusi to'g'ri da'volarni embedding ajrata olmaydi (ikkala tilda ham) — raqam tekshiruvi ushlaydi.",
          "* Yangi BM25 indeksi `data/index/bm25_new` da qurilgan va `data/index/bm25` ga almashtirildi (eski nusxa `bm25_old`); "
          "ishlab turgan server qayta ishga tushirilguncha xotiradagi eski indeks bilan ishlaydi.", ""]
    return "\n".join(L)


def web_extras() -> dict:
    """/api/eval uchun: baseline_v2 (yengil: savollar matnisiz) va ishonch kalibrlash xulosasi."""
    out: dict = {"baseline_v2": None, "trust_cal": None}
    b = _load(EVAL_DIR / "baseline_v2.json")
    if b and "by_split" in b:
        out["baseline_v2"] = {
            "meta": {k: b["meta"].get(k) for k in ("created", "commit", "n_questions", "params")},
            "by_split": b["by_split"],
            "ranks": {q["id"]: (q["modes"].get("hybrid", {}).get("metrics") or {}).get("rank")
                      for q in b["questions"] if q["answerable"]}}
    cal = _load(EVAL_DIR / "trust_calibration.json")
    if cal:
        rows, best, old = cal["rows"], cal["best"], cal["old"]

        def cnt(kinds, prm):
            rs = [x for x in rows if x["kind"] in kinds]
            return [sum(_sup(x, prm) for x in rs), len(rs)]

        def dist(kind, key):
            c = {"high": 0, "medium": 0, "low": 0}
            for k, v in cal["levels"].items():
                if k.startswith(kind + ":") and v[key]:
                    c[v[key]] += 1
            return c
        out["trust_cal"] = {
            "params": {"old": old, "new": {k: best[k] for k in ("ok", "num", "ctx")}},
            "ru_true": {"before": cnt(("ru_real", "ru_trans"), old), "after": cnt(("ru_real", "ru_trans"), best)},
            "ru_false": {"before": cnt(("false_ru",), old), "after": cnt(("false_ru",), best)},
            "uz_false": cnt(("false_uz",), old),
            "levels": {k: {"before": dist(k, "before"), "after": dist(k, "after")} for k in ("ru_real", "uz_real")}}
    return out


def _sup(x: dict, prm: dict) -> bool:
    """scripts/calibrate_trust.supported bilan bir xil (report uchun nusxa)."""
    cos = x["cos_ctx"] if prm["ctx"] and (x["lang"] == "ru" or prm.get("ctx_all")) else x["cos"]
    nums, missing = (x["nums_old"], x["missing_old"]) if prm.get("old_nums") else (x["nums"], x["missing"])
    if missing:
        return False
    if x["lang"] == "ru":
        return cos >= prm["ok"] or (bool(nums) and cos >= prm["num"])
    from . import trust
    return cos >= trust.COS_OK or (x["lex"] is not None and any(x["lex"] >= lx and cos >= cx for lx, cx in trust.LEX_TIERS))
