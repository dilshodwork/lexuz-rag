"""2-bosqich sinovlari, LLM'siz:

    .venv/bin/python scripts/test_stage2.py            # hammasi (trust uchun indeks va bge-m3 yuklanadi, ~10 s)
    .venv/bin/python scripts/test_stage2.py --fast     # indekssiz qismlar

* lotin -> kirill (translit.lat_to_cyr) va oqimda bo'lib o'girish bir xil natija beradi;
* til aniqlash (lotin / kirill / rus);
* <<<KEYINGI>>> ajratgichi oqimning har xil bo'linishida ham ko'rinmaydi;
* murakkab savolni bo'lish evristikasi;
* brauzerdagi nusxa (web/src/textproc.ts, node bilan) server nusxasi bilan aynan bir xil natija beradi;
* ishonch tekshiruvi (trust.check): qo'lda yozilgan to'g'ri va ataylab buzilgan javoblarda.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag.lang import FollowupSplitter, detect_lang, parse_followups  # noqa: E402
from lexrag.plan import split_question  # noqa: E402
from lexrag.translit import LatToCyrStream, lat_to_cyr  # noqa: E402

results: list[tuple[bool, str]] = []


def ok(cond, name, info=""):
    results.append((bool(cond), name))
    print(f"{'OK  ' if cond else 'XATO'} {name}" + (f" — {info}" if info else ""), flush=True)


TRANSLIT = {
    "Oʻzbekiston Respublikasi Mehnat kodeksining 217-moddasiga koʻra [1], yillik taʼtil 21 kalendar kundan kam boʻlmaydi [2][3].":
        "Ўзбекистон Республикаси Меҳнат кодексининг 217-моддасига кўра [1], йиллик таътил 21 календар кундан кам бўлмайди [2][3].",
    "**Qisqa javob:** yer, obyekt, Konstitutsiya, kompensatsiya, muddatsiz, yoʻl, yoki, ega, maʼlumot, gʻalla, SHARTNOMA, IV bob, https://lex.uz/docs/1#2":
        "**Қисқа жавоб:** ер, объект, Конституция, компенсация, муддатсиз, йўл, ёки, эга, маълумот, ғалла, ШАРТНОМА, IV боб, https://lex.uz/docs/1#2",
    "Shu bilan birga, iyerarxiya, poyezd, Chorshanba, OʻZBEKISTON, xodim, huquq, 1-qism":
        "Шу билан бирга, иерархия, поезд, Чоршанба, ЎЗБЕКИСТОН, ходим, ҳуқуқ, 1-қисм",
}
LANGS = {
    "Yillik mehnat taʼtili necha kun?": "uz", "Ажралиш учун қандай ҳужжатлар керак?": "uz_cyr",
    "Президент неча йилга сайланади?": "uz_cyr", "Ажралиш учун кандай хужжатлар керак?": "uz_cyr",
    "Сколько дней длится ежегодный трудовой отпуск?": "ru", "На какой срок избирается Президент?": "ru",
    "Какие документы нужны для развода?": "ru", "Можно ли уволить беременную женщину?": "ru",
    "Ota-onaning huquqlari nima?": "uz",
}
SPLIT = {
    "Ishdan boʻshatilganda qanday kompensatsiya toʻlanadi va mehnat daftarchasi qachon beriladi?": 2,
    "Yillik taʼtil necha kun? Uni boʻlib olish mumkinmi?": 2,
    "Ijara shartnomasi qanday shaklda tuziladi hamda uni bekor qilish uchun nima kerak?": 2,
    "Сколько дней отпуск и можно ли его разделить на части?": 2,
    "Ota va ona huquqlari qanday?": 0, "Yillik mehnat taʼtili necha kun?": 0,
    "Mehnat va ijtimoiy himoya vazirligi qayerda joylashgan?": 0,
}
ANSWER = ("Yillik asosiy taʼtil kamida 21 kalendar kun [1].\n\n- Oʻn sakkiz yoshgacha boʻlganlarga 30 kun [2].\n\n"
          "**<<<KEYINGI>>>**\nTaʼtilni boʻlib olish mumkinmi?\n- Qoʻshimcha taʼtil kimlarga beriladi?\n3. Taʼtil puli qachon toʻlanadi?")


def chunks(text: str, seed: int) -> list[str]:
    rnd = random.Random(seed)
    out, i = [], 0
    while i < len(text):
        j = i + rnd.randint(1, 9)
        out.append(text[i:j])
        i = j
    return out


def py_stream(pieces: list[str], cyr: bool) -> dict:
    sp, tr = FollowupSplitter(), (LatToCyrStream() if cyr else None)
    out = ""
    for p in pieces:
        x = sp.feed(p)
        out += tr.feed(x) if tr else x
    x = sp.flush()
    out += (tr.feed(x) + tr.flush()) if tr else x
    f = sp.followups()
    return {"text": out, "followups": [lat_to_cyr(y) for y in f] if cyr else f}


def phase_unit():
    for src, want in TRANSLIT.items():
        got = lat_to_cyr(src)
        ok(got == want, "lotin -> kirill", got if got != want else src[:50])
    bad = [s for s in range(40) if py_stream(chunks(ANSWER, s), True)["text"] != lat_to_cyr(py_stream([ANSWER], False)["text"])]
    ok(not bad, "kirill oqim: bo'lib o'girish = butun o'girish (40 xil bo'linish)")
    for q, want in LANGS.items():
        ok(detect_lang(q) == want, f"til: {want}", q)
    vis = {py_stream(chunks(ANSWER, s), False)["text"] for s in range(60)}
    ok(vis == {"Yillik asosiy taʼtil kamida 21 kalendar kun [1].\n\n- Oʻn sakkiz yoshgacha boʻlganlarga 30 kun [2]."},
       "<<<KEYINGI>>> qismi oqimda ko'rinmaydi (60 xil bo'linish)", repr(list(vis))[:200])
    f = py_stream([ANSWER], False)["followups"]
    ok(len(f) == 3 and f[1] == "Qoʻshimcha taʼtil kimlarga beriladi?", "keyingi savollar: 3 ta, belgilarsiz", str(f))
    ok(parse_followups('["Birinchi savol?", "Ikkinchi savol?"]') == ["Birinchi savol?", "Ikkinchi savol?"], "keyingi savollar: JSON ham")
    for q, n in SPLIT.items():
        parts = split_question(q)
        ok(len(parts) == n, f"bo'lish: {n} qism", f"{q} -> {parts}")


NODE = """
import { latToCyr, AnswerStream, parseFollowups } from %s;
const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));
""".strip()


def phase_parity():
    """web/src/textproc.ts ni node bilan ishga tushirib, server natijasi bilan solishtirish."""
    cases = [{"pieces": chunks(ANSWER, s), "cyr": s % 2 == 0} for s in range(12)]
    cases += [{"pieces": [t], "cyr": True} for t in TRANSLIT]
    payload = json.dumps({"cases": cases, "followups": ['["A savol?", "B savol?"]', "\n1. Bir savol bor?\n- Ikki savol bor?"]})
    script = (
        f"import {{ AnswerStream, parseFollowups }} from {json.dumps((ROOT / 'web/src/textproc.ts').as_uri())};\n"
        "import { readFileSync } from 'node:fs';\n"
        "const inp = JSON.parse(readFileSync(0, 'utf8'));\n"
        "const out = inp.cases.map((c) => { const s = new AnswerStream(c.cyr ? { marker: '', translit: 'lat2cyr' } : null);\n"
        "  let t = ''; for (const p of c.pieces) t += s.feed(p); t += s.flush(); return { text: t, followups: s.followups() }; });\n"
        "console.log(JSON.stringify({ out, f: inp.followups.map(parseFollowups) }));\n")
    p = subprocess.run(["node", "--input-type=module", "-e", script], input=payload, capture_output=True, text=True)
    if p.returncode:
        ok(False, "node textproc.ts ishga tushdi", p.stderr[:400])
        return
    js = json.loads(p.stdout)
    py = [py_stream(c["pieces"], c["cyr"]) for c in cases]
    diff = [i for i, (a, b) in enumerate(zip(py, js["out"])) if a != b]
    ok(not diff, f"brauzer (textproc.ts) = server: {len(cases)} ta oqim", "" if not diff else f"{py[diff[0]]} != {js['out'][diff[0]]}")
    pf = [parse_followups(x) for x in json.loads(payload)["followups"]]
    ok(pf == js["f"], "brauzer = server: keyingi savollar parseri", f"{pf} / {js['f']}")


def phase_trust():
    """Qo'lda yozilgan to'g'ri va ataylab buzilgan da'volar (haqiqiy manbalar bilan, LLM'siz)."""
    from lexrag import rag, trust
    p = rag.prepare("Yillik mehnat taʼtili necha kun?")
    ids = [s["chunk_id"] for s in p["sources"]]
    by_art = {s["article_number"]: s["n"] for s in p["sources"]}
    n220, n418, n216 = by_art.get("220"), by_art.get("418"), by_art.get("216")
    if not (n220 and n418 and n216):
        ok(False, "trust: kutilgan manbalar topildi (220, 418, 216-moddalar)", str(by_art))
        return
    good = (f"Xodimga bitta tashkilotda ishlagan har besh yil uchun ikki kalendar kunlik qoʻshimcha taʼtil beriladi, "
            f"lekin jami sakkiz kundan oshmaydi [{n220}]. Oʻn sakkiz yoshgacha boʻlgan xodimlarga kamida 30 kalendar "
            f"kunlik yillik taʼtil beriladi [{n418}]. Har yilgi mehnat taʼtili ish oʻrni va oʻrtacha ish haqi saqlangan "
            f"holda beriladi [{n216}].")
    bad = (f"Oʻn sakkiz yoshgacha boʻlgan xodimlarga kamida 45 kalendar kunlik taʼtil beriladi [{n418}]. "
           f"Ish beruvchi xodimga taʼtil uchun yiliga ikki marta bepul sayohat yoʻllanmasi berishi shart [{n216}]. "
           f"Taʼtil vaqtida xodim boshqa ish beruvchida ishlashi qatʼiyan taqiqlanadi [{n216}].")
    r = trust.check(good, ids, "uz")
    ok(r["level"] == "high" and r["supported"] == 3, "trust: to'g'ri javob -> Yuqori", f"{r['supported']}/{r['checked']}")
    r = trust.check(bad, ids, "uz")
    ok(r["level"] == "low" and r["supported"] == 0, "trust: buzilgan javob -> Past, 3 gap ham belgilandi",
       f"{r['supported']}/{r['checked']}: " + "; ".join(", ".join(c["reasons"]) for c in r["claims"]))
    ok(any("45 raqami manbada yoʻq" in c["reasons"] for c in r["claims"]), "trust: o'zgartirilgan raqam (45) aniqlandi")
    r = trust.check(lat_to_cyr(good), ids, "uz_cyr")
    ok(r["level"] == "high", "trust: kirill javob ham (lotinga o'girib tekshiriladi)")
    mixed = good + "\n\n- " + bad.split(". ")[0] + "."
    r = trust.check(mixed, ids, "uz")
    weak = [c for c in r["claims"] if not c["ok"]]
    ok(r["level"] == "medium" and len(weak) == 1 and mixed[weak[0]["start"]:].startswith("Oʻn sakkiz yoshgacha boʻlgan xodimlarga kamida 45"),
       "trust: aralash javob -> O'rta, asossiz gap o'rni to'g'ri (ro'yxat belgisisiz)", f"{r['level']} {r['supported']}/{r['checked']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    phase_unit()
    phase_parity()
    if not a.fast:
        phase_trust()
    bad = [n for c, n in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} o'tdi")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
