"""Javob tili va javob oxiridagi "keyingi savollar" bo'limi.

* detect_lang: savol tili - "uz" (o'zbek lotin), "uz_cyr" (o'zbek kirill), "ru" (rus). LLM'siz: belgilar va
  tez-tez uchraydigan so'zlar bo'yicha.
* Keyingi savollar QO'SHIMCHA LLM SO'ROVISIZ: asosiy javob oxirida LLM `<<<KEYINGI>>>` ajratgichidan keyin
  2-3 ta savol yozadi. FollowupSplitter oqimda ajratgichni (va undan keyingi qismni) foydalanuvchiga
  ko'rsatmaydi. Brauzerdagi nusxasi: web/src/textproc.ts (o'z kaliti bilan oqim brauzerda o'qiladi).
* ru_bm25_terms: ruscha savol uchun BM25 so'zlari (kichik lug'at, LLM'siz).
"""
from __future__ import annotations

import json
import re

LANGS = ("uz", "uz_cyr", "ru")
LANG_NAMES = {"uz": "oʻzbekcha", "uz_cyr": "oʻzbekcha (kirill)", "ru": "ruscha"}

_CYR = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳ]")
_LAT = re.compile(r"[A-Za-z]")
_UZ_ONLY = re.compile(r"[ЎўҚқҒғҲҳ]")
_RU_ONLY = re.compile(r"[ЫыЩщ]")
_WORD = re.compile(r"[а-яёўқғҳ]+")
# rus tilida juda ko'p uchraydigan qisqa so'zlar (o'zbek kirillda deyarli yo'q)
RU_WORDS = set("""и в во на не что как какой какая какие каков сколько можно ли для при или есть это его ее её их
мне меня если то же по из от до за под над о об про у бы был была были будет нужно надо должен должна
кто где когда почему зачем чем чтобы также только уже еще ещё который которые свой своего после без
лет год года дней день срок права право закон закона кодекс кодекса статья статьи""".split())
# o'zbek kirillda tez-tez uchraydigan so'zlar va qo'shimchalar (ў қ ғ ҳ bo'lmasa ham)
UZ_WORDS = set("""ва учун нима неча нечта канча қанча кандай қандай ким қачон қаерда қайси бўлади булади
мумкин мумкинми керак керакми эмас бор йўқ йук билан ҳам хам ёки агар қилиш килиш бериш олиш
йил йилга кун кунга ой ойга""".split())
_UZ_SUFFIX = re.compile(r"(лар|ларни|нинг|дан|даги|га|ни|ми|ади|йди|иш|ган|моқда|мокда|лик|чи|сиз)$")


def detect_lang(q: str) -> str:
    cyr, lat = len(_CYR.findall(q)), len(_LAT.findall(q))
    if cyr < 3 or cyr < lat:
        return "uz"
    if _UZ_ONLY.search(q):
        return "uz_cyr"
    words = _WORD.findall(q.lower())
    ru = sum(w in RU_WORDS for w in words) + 2 * len(_RU_ONLY.findall(q))
    ru += sum(1 for w in words if re.search(r"(ться|тся|ого|его|ому|ием|ией|ость|ости|ует|ают|яет)$", w))
    uz = sum(w in UZ_WORDS for w in words)
    uz += sum(1 for w in words if len(w) > 3 and w not in RU_WORDS and _UZ_SUFFIX.search(w))
    return "ru" if ru > uz else "uz_cyr"


def script_of(q: str) -> str:
    """Savol yozuvi (X-ray uchun): kirill | lotin."""
    return "kirill" if len(_CYR.findall(q)) > len(_LAT.findall(q)) else "lotin"


def resolve_lang(question: str, pref: str | None) -> str:
    """Foydalanuvchi sozlamasi (auto | uz | uz_cyr | ru) -> javob tili."""
    return pref if pref in LANGS else detect_lang(question)


# ---------------------------------------------------------------- "topilmadi" iborasi
# LLM manbalarda javob topmasa shu iborani yozadi (rag.SYSTEM, 4-qoida). Kirill javobda LLM baribir lotinda
# yozadi, shuning uchun tekshiruv o'girishdan oldingi matnda qilinadi.
NOT_FOUND_RE = re.compile(r"^\W*(Bazadagi hujjatlarda bu savolga[^.]*topilmadi|В базе не найден)", re.I)

# ---------------------------------------------------------------- keyingi savollar
MARKER = "<<<KEYINGI>>>"
_MARKER_RE = re.compile(r"\**\s*<{2,3}\s*(?:KEYINGI|КЕЙИНГИ)\s*>{2,3}\s*\**", re.I)
_HOLD = 24  # ajratgich bo'laklar orasida uzilishi mumkin: oxirgi "<" dan keyingi qism ushlab turiladi


class FollowupSplitter:
    """Oqim filtri: feed() ajratgichgacha bo'lgan matnni qaytaradi, keyingi qism self.tail da yig'iladi."""

    def __init__(self):
        self.buf = ""
        self.tail: str | None = None

    def feed(self, piece: str) -> str:
        if self.tail is not None:
            self.tail += piece
            return ""
        self.buf += piece
        m = _MARKER_RE.search(self.buf)
        if m:
            out, self.tail = self.buf[:m.start()], self.buf[m.end():]
            self.buf = ""
            return out.rstrip(" *\n")
        lt = self.buf.find("<", max(0, len(self.buf) - _HOLD))
        if lt < 0:
            lt = len(self.buf)
        # oxiridagi bo'sh joy va "**" ham ushlab turiladi: ajratgich "**<<<KEYINGI>>>**" bo'lib kelishi mumkin
        tail = len(self.buf[:lt].rstrip(" \n*"))
        out, self.buf = self.buf[:tail], self.buf[tail:]
        return out

    def flush(self) -> str:
        out, self.buf = self.buf, ""
        return out

    def followups(self) -> list[str]:
        return parse_followups(self.tail or "")


def parse_followups(tail: str) -> list[str]:
    """Ajratgichdan keyingi qism: JSON ro'yxat yoki har qatorda bitta savol. 2-3 ta savol qaytaradi."""
    t = tail.strip()
    items: list[str] = []
    if t.startswith("["):
        try:
            items = [str(x) for x in json.loads(t[: t.rfind("]") + 1])]
        except (ValueError, TypeError):
            items = []
    if not items:
        items = t.splitlines()
    out = []
    for x in items:
        x = re.sub(r"^\s*(?:[-*•–]|\d+[.)])\s*", "", x).strip().strip('"«»“”*').strip()
        x = re.sub(r"\[\d+\]", "", x).strip()
        if x and x[-1] not in "?.!":
            x += "?"
        if 6 <= len(x) <= 160 and x not in out:
            out.append(x)
    return out[:3]


def split_followups(text: str) -> tuple[str, list[str]]:
    """To'liq javob matni -> (ko'rinadigan javob, keyingi savollar)."""
    m = _MARKER_RE.search(text)
    if not m:
        return text, []
    return text[:m.start()].rstrip(" *\n"), parse_followups(text[m.end():])


# ---------------------------------------------------------------- ruscha savol uchun BM25
# Ruscha so'z boshi -> o'zbekcha atama. Lug'atda bo'lmasa ham qidiruv ishlaydi (bge-m3 ko'p tilli),
# lug'at faqat BM25 ga aniq atama beradi.
RU_GLOSSARY = {
    "отпуск": "taʼtil", "трудов": "mehnat", "работник": "xodim", "работодател": "ish beruvchi",
    "зарплат": "ish haqi", "заработн": "ish haqi", "уволь": "mehnat shartnomasini bekor qilish",
    "увольн": "mehnat shartnomasini bekor qilish", "развод": "nikohdan ajratish ajralish", "брак": "nikoh",
    "супруг": "er-xotin", "алимент": "aliment", "ребен": "bola", "дет": "bola", "наслед": "meros",
    "завещ": "vasiyatnoma", "аренд": "ijara", "договор": "shartnoma", "купл": "oldi-sotdi", "продаж": "oldi-sotdi",
    "налог": "soliq", "штраф": "jarima", "суд": "sud", "срок": "muddat", "президент": "Prezident",
    "избира": "saylanadi saylov", "выбор": "saylov", "водител": "haydovchi haydovchilik", "удостоверени": "guvohnoma",
    "пенси": "pensiya", "собственност": "mulk", "земел": "yer", "земл": "yer", "жил": "uy-joy",
    "квартир": "kvartira uy-joy", "кредит": "kredit", "банк": "bank", "пособи": "nafaqa", "инвалид": "nogironlik",
    "гражданств": "fuqarolik", "паспорт": "pasport", "несовершеннолет": "voyaga yetmagan", "уголовн": "jinoyat",
    "преступлен": "jinoyat", "наказани": "jazo", "административ": "maʼmuriy", "ответственност": "javobgarlik",
    "взятк": "pora", "краж": "oʻgʻrilik", "опек": "vasiylik", "усыновл": "farzandlikka olish",
    "рабоч": "ish", "сверхурочн": "ish vaqtidan tashqari", "беременн": "homiladorlik", "материн": "onalik",
    "компенсац": "kompensatsiya", "книжк": "daftarcha", "потребител": "isteʼmolchi", "товар": "tovar",
    "нотари": "notarius", "конституц": "Konstitutsiya", "закон": "qonun", "предпринимател": "tadbirkorlik",
    "лиценз": "litsenziya", "регистрац": "roʻyxatdan oʻtkazish", "дней": "kun", "дня": "kun", "лет": "yil",
    "сокращ": "qisqartirish", "испытат": "sinov", "ежегодн": "yillik", "минимальн": "eng kam",
}


def ru_bm25_terms(q: str) -> str:
    words = _WORD.findall(q.lower())
    terms = []
    for w in words:
        for stem, uz in RU_GLOSSARY.items():
            if w.startswith(stem) and uz not in terms:
                terms.append(uz)
    return " ".join(terms)
