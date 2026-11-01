"""O'zbek lotin uchun oddiy qoidaga asoslangan o'zak ajratuvchi (BM25 tokenizatori) va stopwordlar.

Nega kerak: o'zbek tili qo'shimchali - "taʼtil", "taʼtilni", "taʼtilining", "taʼtillari" BM25 uchun boshqa-boshqa
so'zlar. Oldingi usul so'zni birinchi 7 harfgacha kesardi: "taʼtilining" -> "taʼtili" va "taʼtil" -> "taʼtil" mos
kelmaydi, qisqa so'zlar esa umuman qisqarmaydi ("ishni" va "ish"). Bu modul qo'shimchalarni o'ngdan chapga
(so'z yasovchi -> ko'plik -> egalik -> kelishik -> yuklama tartibining teskarisi) olib tashlaydi.

Qoidalar:
  * fold(): kichik harf, ʻ va ʼ (va ' ` ‘ ’) olib tashlanadi - "oʻgʻirlik", "o'g'irlik", "ogirlik" bir xil token.
    Kirill savoldan o'girilgan yoki apostrofsiz yozilgan savollar ham shu bilan moslashadi.
  * Qo'shimcha faqat qolgan o'zak MIN_STEM (3) harfdan qisqa bo'lmasa olinadi; bir harfli "-i" va "-im",
    "-ing" kabi xavfli qo'shimchalar uchun o'zak kamida 4 harf.
  * KEEP - qo'shimchaga o'xshab tugaydigan, lekin o'zi o'zak bo'lgan so'zlar (xodim, hokim, taʼlim, ...).
  * Har so'zdan ko'pi bilan MAX_STRIP ta qo'shimcha olinadi.
  * Stopwordlar (savol so'zlari, bog'lovchilar, ko'makchilar) o'zak holida tashlanadi. Huquqiy umumiy so'zlar
    ("modda", "qonun", "kodeks") alohida ro'yxatda - ularni tashlash eval/ DEV qismida sweep bilan tanlanadi.

Faqat lotin uchun: kirill savol avval translit.cyr_to_lat bilan lotinga o'giriladi (retrieval.prepare_query).
"""
from __future__ import annotations

import re
from functools import lru_cache

from .normalize import normalize_text

APOS = "ʻʼ'`‘’´"
_APOS_RE = re.compile(f"[{APOS}]")
WORD = re.compile(r"[a-zʻʼ'`‘’´0-9¹²³⁴⁵⁶⁷⁸⁹⁰]+")

MIN_STEM = 3
MAX_STRIP = 4

# Qo'shimchalar fold() qilingan holda (apostrofsiz). Har guruh ichida uzunidan qisqasiga qarab tekshiriladi.
# (qo'shimcha, o'zakning minimal uzunligi)
def _by_len(xs: list[str]) -> list[str]:
    return sorted(xs, key=len, reverse=True)


_PARTICLE = _by_len(["mi", "ku", "dir", "gina", "kina", "qina"])
_CASE = _by_len(["gacha", "kacha", "qacha", "dagi", "tagi", "ning", "dan", "tan", "ni", "ga", "ka", "qa", "da", "ta",
                 "dek", "day", "cha"])
_POSS = _by_len(["imiz", "ingiz", "lari", "miz", "ngiz", "ing", "im", "si", "i"])
_PLURAL = ["lar"]
_VERB = _by_len(["moqchi", "moqda", "ayotgan", "yotgan", "adigan", "ydigan", "digan", "masdan", "magan", "mayman",
                 "aman", "ilgan", "ingan", "lgan", "ngan", "gan", "kan", "qan", "iladi", "inadi", "adi", "ydi", "di",
                 "ishi", "ish", "shi", "sh", "ib", "sam", "sak", "sangiz", "sang", "sa", "may", "mas", "masa"])
# majhul nisbat: faqat fe'l qo'shimchasi olingandan keyin ("beril|adi", "toʻlan|adi", "belgilan|gan")
_PASSIVE = ["il", "in", "n"]
_DERIV = _by_len(["chilik", "lik", "lig", "chi", "siz", "li"])

# xavfli qo'shimchalar: o'zak kamida shuncha harf (qolganlari MIN_STEM)
_MIN_FOR = {"im": 4, "ing": 4, "di": 4, "sh": 4, "ib": 4, "sa": 4, "ta": 4, "ka": 4, "qa": 4, "cha": 4, "mi": 4,
            "chi": 4, "li": 4, "shi": 4, "may": 4, "mas": 4, "ku": 4, "adi": 2, "ydi": 2}

# o'zi o'zak bo'lgan so'zlar: qo'shimcha olinmaydi. Qo'shimchaga o'xshab tugaydigan (-im, -da, -i, -lar, -chi ...)
# va huquqiy matnda tez-tez uchraydigan o'zaklar.
KEEP = {_APOS_RE.sub("", w) for w in """xodim hokim taʼlim muallim hakim rahim olim qadim taqsim taslim tanzim
qoida foyda fayda dollar kishi qozi vali tarbiyachi ishchi haydovchi isteʼmolchi qarzdor nafaqa pensiya
oila sudya bola ona ota aka uka opa kasbi jazo vazir prokuror militsiya politsiya kvartira mashina summa
qonun shaxs bayon majlis organ tuman kodeks rais asos meros matn karantin xotin tashabbus imkon kompleks mazmun
orden notarius kengash jarayon mutaxassis tovon maydon ombudsman muassis telefon balans iltimos unvon protsess
tashxis voris tomon kurs yakun resurs oldin mumkin inson zamon vatan
""".split()}
# n/s bilan tugaydigan o'zaklar ("qonun|i", "shaxs|i") korpusdan topildi: o'zak va o'zak+"i" ikkalasi ko'p uchraydi,
# aks holda "-ni" / "-si" kelishik deb olinib "qonu", "shax" qolardi.


_VERB_I = [s for s in _VERB if s.endswith("i") and len(s) >= 3]
_ALL = _by_len(set(_PARTICLE + _CASE + _POSS + _PLURAL + _VERB + _DERIV))


def fold(word: str) -> str:
    return _APOS_RE.sub("", word.lower())


def _strip_one(w: str, sufs: list[str]) -> str | None:
    for s in sufs:
        if w.endswith(s) and len(w) - len(s) >= _MIN_FOR.get(s, MIN_STEM):
            return w[: -len(s)]
    return None


@lru_cache(maxsize=500_000)
def stem(word: str, deriv: bool = False) -> str:
    """Bitta so'z (lotin) -> o'zak. deriv=True: so'z yasovchi (-lik, -chi, -siz, -li) ham olinadi."""
    w = fold(word)
    if not w or w in KEEP or any(c.isdigit() for c in w):
        return w
    groups = [_PARTICLE, _CASE, _POSS, _PLURAL] + ([_DERIV] if deriv else [])
    n, verb = 0, False
    changed = True
    while changed and n < MAX_STRIP and w not in KEEP:
        changed = False
        # qo'shimcha olinganda KEEP dagi o'zak qolsa - shu ustun ("taʼlimi" -> "taʼlim", "-mi" yuklama emas)
        keep = next((w[: -len(s)] for s in _ALL if w.endswith(s) and w[: -len(s)] in KEEP), None)
        if keep:
            w, n = keep, n + 1
            break
        # "i" bilan tugaydigan fe'l qo'shimchalari egalik "-i" dan oldin: "berilADI", "ishlaYDI", "boʻshatMOQCHI"
        nw = None if verb else _strip_one(w, _VERB_I)
        if nw is not None:
            w, n, changed, verb = _passive(nw), n + 1, True, True
            continue
        for g in groups:
            if g is _POSS and w.endswith("chi"):
                g = [s for s in g if s != "i"]           # "ijarachi", "beruvchi": -chi yasovchi, "-i" egalik emas
            nw = _strip_one(w, g)
            if nw is not None:
                w, n, changed = nw, n + 1, True
                break
        if not changed and not verb:
            nw = _strip_one(w, _VERB)
            if nw is not None:
                w, n, changed, verb = _passive(nw), n + 1, True, True
    return w


def _passive(w: str) -> str:
    for p in _PASSIVE:
        # "n" faqat unlidan keyin: toʻlan -> toʻla, belgilan -> belgila
        if w.endswith(p) and len(w) - len(p) >= MIN_STEM and (p != "n" or w[-2] in "aeiou"):
            return w[: -len(p)]
    return w


# ---------------------------------------------------------------- stopwordlar
# savol so'zlari, bog'lovchilar, ko'makchilar, olmoshlar, yordamchi fe'llar (lotin, apostrof bilan yoki siz)
STOP_BASIC = """uchun qanday qancha qanaqa necha nechta nechanchi nima nimalar nega nimaga qaysi kim kimlar kimga qachon
qayerda qayerga qayerdan qanchalik bilan va yoki hamda ham esa lekin ammo biroq agar bo'lsa bo'ladi bo'ladimi
bo'lishi bo'lib bo'lgan bo'lmasa kerak kerakmi mumkin mumkinmi shart shartmi bormi bor yo'q yo'qmi emas emasmi
edi ekan deb deyiladi qilib etib bu shu o'sha u ular men meni menga mening biz bizga bizning siz sizga sizning
uni unga uning o'z o'zi har bir hech faqat eng juda ko'p kam keyin oldin ichida qadar gacha orqali haqida
bo'yicha ko'ra tomonidan kabi yana endi hali allaqachon ya'ni masalan qilish qiladi qilinadi beriladi""".split()
STOP_LEGAL = """modda moddasi qonun qonuni kodeks kodeksi respublika respublikasi o'zbekiston""".split()


@lru_cache(maxsize=4)
def stop_stems(legal: bool = False, deriv: bool = False) -> frozenset[str]:
    words = STOP_BASIC + (STOP_LEGAL if legal else [])
    return frozenset(stem(normalize_text(w), deriv) for w in words)


def tokenize(text: str, stop: str = "basic", deriv: bool = False, trunc: int | None = None) -> list[str]:
    """Matn -> BM25 tokenlari. stop: none | basic | legal (basic + huquqiy umumiy so'zlar).
    trunc: o'zakni yana shuncha harfgacha kesish (None - kesilmaydi)."""
    t = normalize_text(text).lower()
    stops = frozenset() if stop == "none" else stop_stems(stop == "legal", deriv)
    out = []
    for w in WORD.findall(t):
        if len(w) < 2 and not w.isdigit():
            continue
        s = stem(w, deriv)
        if not s or s in stops:
            continue
        if trunc and len(s) > trunc:
            s = s[:trunc]
        out.append(s)
    return out
