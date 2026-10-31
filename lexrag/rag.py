"""RAG: savol -> tahlil -> gibrid qidiruv (kerak bo'lsa bir nechta) -> manbali kontekst -> LLM javobi.

Barcha promptlar shu faylda (server kaliti va brauzerdagi o'z kaliti yo'li bir xil promptni oladi):
* system_prompt(lang, mode): "legal" - yuridik javob + oxirida keyingi savollar; "simple" - sodda tilda.
* Faqat berilgan manbalar asosida javob; har bir da'vodan keyin [n] iqtibos.
* Manbalarda javob bo'lmasa - ochiq aytadi, o'zidan to'qimaydi.
* Eng yaqin manba juda uzoq bo'lsa (cosine < NO_ANSWER_COS), LLM chaqirilmaydi.

prepare_steps() - generator: ("step", {...}) bosqichlarini (ekranda ko'rinadi) va oxirida ("result", {...})
qaytaradi. /api/ask ularni SSE bilan oqimda yuboradi, /api/context ro'yxat qilib qaytaradi.
"""
from __future__ import annotations

import re
import time
from typing import Iterator

from . import llm, plan
from .lang import LANG_NAMES, MARKER, NOT_FOUND_RE, FollowupSplitter, resolve_lang
from .retrieval import get_chunks, hybrid_search, prepare_query
from .translit import LatToCyrStream, cyr_to_lat

K_CONTEXT = 8
K_SPLIT = 10          # savol bo'linganda manbalar soni
NO_ANSWER_COS = 0.45  # eval natijasiga qarab sozlanadi
RRF_K = 60

_LANG_RULE = {
    "uz": "Faqat oʻzbek tilida (lotin yozuvida) javob ber.",
    # kirill javob: LLM lotinda yozadi, keyin translit.lat_to_cyr bilan o'giriladi ([n] va raqamlar buzilmaydi)
    "uz_cyr": "Faqat oʻzbek tilida, LOTIN yozuvida javob ber (matn keyin avtomatik kirillga oʻgiriladi).",
    "ru": ("Javobni RUS tilida yoz (Отвечай на русском языке). Manbalar oʻzbekcha: mazmunini aniq tarjima qil, "
           "hujjat nomini ruscha ber (masalan, «Трудовой кодекс»), modda raqamlarini oʻzgartirma."),
}
_NOT_FOUND = {
    "uz": "Bazadagi hujjatlarda bu savolga aniq javob topilmadi.",
    "uz_cyr": "Bazadagi hujjatlarda bu savolga aniq javob topilmadi.",
    "ru": "В базе не найден точный ответ на этот вопрос.",
}
_FOLLOW_LANG = {"uz": "oʻzbek tilida (lotin)", "uz_cyr": "oʻzbek tilida (lotin)", "ru": "rus tilida"}

SYSTEM_LEGAL = """Sen Oʻzbekiston Respublikasi qonunchiligi boʻyicha yordamchisan. {lang_rule}

Qatʼiy qoidalar:
1. Faqat quyida berilgan MANBALAR matniga tayan. Oʻzingdan qoida, raqam, muddat yoki modda oʻylab topma.
2. Har bir daʼvodan keyin manba raqamini kvadrat qavsda yoz: [1], [2]. Bir nechta boʻlsa [1][3].
3. Javobda hujjat nomi va modda raqamini aniq ayt (masalan: "Mehnat kodeksining 217-moddasiga koʻra ...").
4. Agar manbalarda savolga javob boʻlmasa yoki yetarli boʻlmasa, javobni aynan shu gap bilan boshla: "{not_found}" va qaysi yoʻnalishda qidirish mumkinligini qisqa koʻrsat. Taxmin qilma.
5. Javob tuzilishi: avval 1-2 gapda qisqa javob, keyin kerak boʻlsa tafsilotlar (roʻyxat boʻlishi mumkin). Ortiqcha kirish soʻzlari yozma.
6. Yuridik maslahat berayotganingni daʼvo qilma; sen qonun matnini tushuntirasan.
7. Javob tugagach, yangi qatorda aynan {marker} deb yoz va undan keyin foydalanuvchi keyin berishi mumkin boʻlgan 3 ta qisqa savolni {follow_lang} har birini alohida qatorda yoz: raqamsiz, belgisiz, iqtibossiz, shu mavzu va manbalar doirasida. Bu qatorlar foydalanuvchiga tugma boʻlib chiqadi."""

SYSTEM_SIMPLE = """Sen qonun matnini oddiy odamga tushuntiradigan yordamchisan. {lang_rule}

Qoidalar:
1. Faqat quyidagi MANBALARga tayan. Yangi qoida, raqam yoki muddat qoʻshma; raqamlarni manbadagidek yoz.
2. Huquqiy atamalarsiz, kundalik tilda yoz: qisqa gaplar, oʻquvchiga "siz" deb murojaat qil. Atamani ishlatsang, qavsda oddiy soʻz bilan tushuntir.
3. Har bir daʼvodan keyin manba raqamini [n] koʻrinishida saqla (raqamlar MANBALAR roʻyxatidagidek).
4. Tuzilishi: 1-2 gapda asosiy javob; keyin "Masalan:" bilan boshlanadigan bitta kundalik misol (oddiy ism va hayotiy vaziyat bilan); oxirida kerak boʻlsa 1-2 ta qisqa "nima qilish kerak" maslahati.
5. Jami 130 soʻzdan oshmasin. Sarlavha, jadval va kirish soʻzlari yozma.
6. Manbalarda javob boʻlmasa, javobni aynan shu gap bilan boshla: "{not_found}"."""


def system_prompt(lang: str = "uz", mode: str = "legal") -> str:
    tpl = SYSTEM_SIMPLE if mode == "simple" else SYSTEM_LEGAL
    return tpl.format(lang_rule=_LANG_RULE[lang], not_found=_NOT_FOUND[lang], marker=MARKER,
                      follow_lang=_FOLLOW_LANG[lang])


# eski nom (CLI va sinovlar uchun)
SYSTEM = system_prompt("uz", "legal")


def format_context(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        body = h["text"].split("\n\n", 1)[-1]
        blocks.append(
            f"[{i}] {h.get('heading', '')}\n"
            f"Holati: {h.get('status', '')}; oxirgi tahrir: {h.get('last_edition_date', '')}; "
            f"manba: {h.get('source_url', '')}\n{body}")
    return "\n\n---\n\n".join(blocks)


def source_cards(hits: list[dict]) -> list[dict]:
    keys = ["chunk_id", "doc_title", "doc_type", "doc_number", "article_number", "article_title", "chapter",
            "section", "status", "last_edition_date", "source_url", "doc_url", "heading", "score", "cosine",
            "rank_dense", "rank_bm25"]
    out = []
    for i, h in enumerate(hits, 1):
        card = {k: h.get(k) for k in keys}
        card["n"] = i
        card["text"] = h["text"].split("\n\n", 1)[-1]
        out.append(card)
    return out


def retrieve(question: str, k: int = K_CONTEXT, **kw) -> list[dict]:
    return hybrid_search(question, k=k, **kw)


NO_ANSWER_TEXT = ("Bazadagi hujjatlarda bu savolga mos qonun normasi topilmadi. "
                  "Savolni aniqroq yozib koʻring (masalan, qaysi soha yoki hujjat haqida).")


def short_doc(title: str) -> str:
    """'OʻZBEKISTON RESPUBLIKASINING MEHNAT KODEKSI' -> 'Mehnat kodeksi' (bosqichlar satri uchun)."""
    t = re.sub(r"\s+", " ", title or "").strip()
    letters = re.sub(r"[^A-Za-z]", "", t)
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = t.lower()
    t = re.sub(r"^oʻzbekiston respublikasi(ning|)\s+", "", t, flags=re.I)
    t = t[:1].upper() + t[1:]
    return t if len(t) <= 42 else t[:40].rstrip() + "…"


def _fuse(lists: list[list[dict]], k: int) -> list[dict]:
    """Bir nechta qidiruv natijasi -> RRF bilan bitta ro'yxat, takrorlarsiz. Har qismning eng yaxshi 2 tasi
    albatta kiradi (aks holda bitta qism boshqasini siqib chiqarishi mumkin)."""
    score: dict[str, float] = {}
    best: dict[str, dict] = {}
    for lst in lists:
        for r, h in enumerate(lst):
            cid = h["chunk_id"]
            score[cid] = score.get(cid, 0.0) + 1 / (RRF_K + r + 1)
            if cid not in best or (h.get("cosine") or 0) > (best[cid].get("cosine") or 0):
                best[cid] = h
    order = sorted(score, key=score.get, reverse=True)
    must = []
    for lst in lists[1:]:
        must += [h["chunk_id"] for h in lst[:2] if h["chunk_id"] not in must]
    top = must[:k]
    top += [c for c in order if c not in top][: k - len(top)]
    top.sort(key=lambda c: -score[c])
    out = []
    for cid in top:
        h = dict(best[cid])
        h["score"] = round(score[cid], 5)
        out.append(h)
    return out


def _step(key: str, label: str, state: str, detail: str = "", ms: int | None = None) -> tuple[str, dict]:
    d = {"key": key, "label": label, "state": state, "detail": detail}
    if ms is not None:
        d["ms"] = ms
    return "step", d


def prepare_steps(question: str, k: int = K_CONTEXT, lang_pref: str | None = None, mode: str = "legal",
                  chunk_ids: list[str] | None = None, base_answer: str | None = None,
                  llm_plan: bool = False, **kw) -> Iterator[tuple[str, dict]]:
    """Bosqichlar + natija. chunk_ids berilsa (sodda rejim) qayta qidirilmaydi: o'sha manbalar, o'sha [n]."""
    question = question.strip()
    lang = resolve_lang(question, lang_pref)
    # LLM'ga beriladigan savol: o'zbekcha kirill -> lotin (lotinda javob yozishi uchun), ruscha - asl holida
    q_llm = question if lang == "ru" else prepare_query(question)
    steps: list[dict] = []

    def done(ev):
        steps.append(ev[1])
        return ev

    if chunk_ids:
        t = time.time()
        yield _step("reuse", "Manbalar qayta ishlatilmoqda", "run")
        hits = get_chunks(chunk_ids)
        yield done(_step("reuse", "Manbalar qayta ishlatilmoqda", "done",
                         f"qayta qidiruvsiz · {len(hits)} ta modda", int((time.time() - t) * 1000)))
        user = f"MANBALAR:\n\n{format_context(hits)}\n\n===\n\nSAVOL: {q_llm}"
        if base_answer:
            base = cyr_to_lat(base_answer) if re.search(r"[ЎўҚқҒғҲҳ]", base_answer) else base_answer
            user += f"\n\nYURIDIK JAVOB (shuni soddaroq tushuntir, [n] lar yuqoridagi manbalarga tegishli):\n{base[:6000]}"
        yield "result", {"sources": source_cards(hits), "no_answer": not hits, "best_cosine": None, "lang": lang,
                         "parts": [], "steps": steps,
                         "prompt": {"system": system_prompt(lang, mode), "user": user} if hits else None}
        return

    # 1. tahlil
    t = time.time()
    yield _step("analyze", "Savol tahlil qilinmoqda", "run")
    parts = plan.llm_split(question) if (llm_plan and plan.llm_enabled()) else plan.split_question(question)
    detail = f"Javob tili: {LANG_NAMES[lang]}"
    if parts:
        detail += f" · {len(parts)} qismga boʻlindi"
    yield done(_step("analyze", "Savol tahlil qilinmoqda", "done", detail, int((time.time() - t) * 1000)))

    # 2. qidiruv (to'liq savol + har qism alohida)
    lists = []
    queries = [question] + parts
    for i, q in enumerate(queries):
        t = time.time()
        label = "Qidirilmoqda" if i == 0 else f"Qidirilmoqda: «{q if len(q) <= 46 else q[:44].rstrip() + '…'}»"
        yield _step(f"search{i}", label, "run")
        res = hybrid_search(q, k=k, lang=lang, **kw)
        lists.append(res)
        docs = []
        for h in res:
            d = short_doc(h.get("doc_title", ""))
            if d not in docs:
                docs.append(d)
        yield done(_step(f"search{i}", label, "done", " · ".join(docs[:2]) + ("…" if len(docs) > 2 else ""),
                         int((time.time() - t) * 1000)))

    # 3. birlashtirish
    t = time.time()
    if parts:
        before = sum(len(x) for x in lists)
        hits = _fuse(lists, max(k, K_SPLIT))
        found_detail = f"{len(queries)} qidiruv birlashtirildi, {before - len(hits)} ta takror olib tashlandi"
    else:
        hits = lists[0]
        n_docs = len({h.get("doc_id") or h.get("doc_title") for h in hits})
        found_detail = f"{n_docs} ta hujjatdan"
    yield done(_step("found", f"{len(hits)} ta modda topildi", "done", found_detail, int((time.time() - t) * 1000)))

    # 4. tekshiruv: eng yaqin moddaning o'xshashligi, holati
    t = time.time()
    yield _step("check", "Tekshirilmoqda", "run")
    best = max((h.get("cosine") or 0) for h in hits) if hits else 0
    no_answer = not hits or best < NO_ANSWER_COS
    active = sum(1 for h in hits if h.get("status") == "amalda")
    if no_answer:
        check_detail = "mos modda yoʻq — taxmin qilinmaydi"
    else:
        check_detail = (f"eng yaqin moslik {round(best * 100)}% · "
                        + ("hammasi amaldagi tahrir" if active == len(hits) else f"{active} tasi amalda"))
    yield done(_step("check", "Tekshirilmoqda", "done", check_detail, int((time.time() - t) * 1000)))

    if no_answer:
        yield "result", {"sources": source_cards(hits[:3]), "no_answer": True, "best_cosine": best, "lang": lang,
                         "parts": parts, "steps": steps, "prompt": None}
        return
    user = f"MANBALAR:\n\n{format_context(hits)}\n\n===\n\nSAVOL: {q_llm}"
    if parts:
        user += "\n\nSavol bir necha qismdan iborat, har biriga alohida javob ber:\n" + \
                "\n".join(f"{i}) {p if lang == 'ru' else prepare_query(p)}" for i, p in enumerate(parts, 1))
    yield "result", {"sources": source_cards(hits), "no_answer": False, "best_cosine": best, "lang": lang,
                     "parts": parts, "steps": steps, "prompt": {"system": system_prompt(lang, mode), "user": user}}


def prepare(question: str, k: int = K_CONTEXT, **kw) -> dict:
    """prepare_steps natijasi (bosqichlar result["steps"] da)."""
    for ev, data in prepare_steps(question, k=k, **kw):
        if ev == "result":
            return data
    raise RuntimeError("prepare_steps natija qaytarmadi")


class AnswerStream:
    """LLM oqimi -> foydalanuvchiga ko'rinadigan matn: <<<KEYINGI>>> qismi ajratiladi, kirill javob o'giriladi.
    raw - LLM yozgan asl matn ("topilmadi" iborasi shunda tekshiriladi)."""

    def __init__(self, lang: str):
        self.split = FollowupSplitter()
        self.cyr = LatToCyrStream() if lang == "uz_cyr" else None
        self.raw = ""

    def feed(self, piece: str) -> str:
        self.raw += piece
        out = self.split.feed(piece)
        return self.cyr.feed(out) if self.cyr else out

    def flush(self) -> str:
        out = self.split.flush()
        return (self.cyr.feed(out) + self.cyr.flush()) if self.cyr else out

    def followups(self) -> list[str]:
        f = self.split.followups()
        if self.cyr:
            from .translit import lat_to_cyr
            f = [lat_to_cyr(x) for x in f]
        return f

    def not_found(self) -> bool:
        return bool(NOT_FOUND_RE.search(self.raw))


def answer_stream(question: str, k: int = K_CONTEXT, **kw) -> tuple[list[dict], Iterator[str]]:
    p = prepare(question, k=k, **kw)
    if p["no_answer"]:
        return p["sources"], iter([NO_ANSWER_TEXT])

    def gen():
        s = AnswerStream(p["lang"])
        for piece in llm.stream(p["prompt"]["system"], p["prompt"]["user"]):
            if out := s.feed(piece):
                yield out
        if out := s.flush():
            yield out
        if f := s.followups():
            yield "\n\nKeyingi savollar:\n" + "\n".join(f"  • {x}" for x in f)
    return p["sources"], gen()


def answer(question: str, **kw) -> dict:
    sources, gen = answer_stream(question, **kw)
    return {"answer": "".join(gen), "sources": sources}


def cli_ask(question: str, k: int = K_CONTEXT):
    import textwrap
    sources, gen = answer_stream(question, k=k)
    print(f"\nSavol: {question}\n")
    for piece in gen:
        print(piece, end="", flush=True)
    print("\n\nManbalar:")
    for s in sources:
        print(f"  [{s['n']}] {s['doc_title'][:70]} - "
              f"{(s['article_number'] + '-modda') if s['article_number'] else s['heading'][-60:]}"
              f"  ({s['status']}, {s['last_edition_date']})")
        print(f"      {s['source_url']}")
    print(textwrap.fill("\nBu yuridik maslahat emas. Rasmiy matn: lex.uz", 100))
