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
from .lang import LANG_NAMES, MARKER, NOT_FOUND_RE, FollowupSplitter, detect_lang, resolve_lang, script_of
from .retrieval import chunk_meta, get_chunks, hybrid_search, prepare_query
from .translit import LatToCyrStream, cyr_to_lat

K_CONTEXT = 8
K_SPLIT = 10          # savol bo'linganda manbalar soni
# eval/sweep.json: javobi bor 46 savolda eng yaqin cosine >= 0.55, bazada yo'q savollarda 0.43-0.45 (+ bitta 0.61).
# 0.45 ham xuddi shu natijani berardi (3/4 rad, 0/46 xato), lekin bitta "yo'q" savol 0.448 da - chegara juda yaqin edi.
NO_ANSWER_COS = 0.48
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


# ---------------------------------------------------------------- X-ray (RAG ichi, faqat so'ralganda)
SPAN_LABELS = {"analyze": "Savol tahlili", "embed": "Embedding (bge-m3)", "dense": "Dense qidiruv (ChromaDB)",
               "bm25": "BM25", "rrf": "RRF birlashtirish", "fetch": "Modda matnlarini olish",
               "fuse": "Qismlarni birlashtirish", "check": "Tekshiruv", "reuse": "Manbalarni olish"}


def _tokens(text: str) -> tuple[int, str]:
    """Taxminiy token soni: bge-m3 (XLM-R) tokenizatori; yuklanmasa belgi/4. LLM tokenizatori boshqacha bo'lishi mumkin."""
    try:
        from .chunker import ntok
        return ntok(text), "bge-m3 tokenizatori"
    except Exception:  # noqa: BLE001 - tokenizator tarmoqsiz yuklanmasa
        return max(1, len(text) // 4), "belgilar / 4"


class XRay:
    """prepare_steps ichida qidiruv tafsilotlarini yig'adi. Faqat xray=True bo'lganda yaratiladi."""

    def __init__(self, question: str, lang: str, lang_pref: str | None, mode: str):
        self.t0 = time.perf_counter()
        self.searches: list[dict] = []
        self.spans: list[dict] = []
        self.d: dict = {
            "question": question, "mode": mode,
            "analysis": {"lang": lang, "lang_name": LANG_NAMES[lang], "detected": detect_lang(question),
                         "forced": lang_pref in ("uz", "uz_cyr", "ru"), "script": script_of(question),
                         "latin": prepare_query(question), "parts": [], "planner": None},
        }

    def span(self, key: str, start: float, end: float | None = None, **extra):
        end = time.perf_counter() if end is None else end
        self.spans.append({"key": key, "label": SPAN_LABELS.get(key, key), "start": round((start - self.t0) * 1000, 1),
                           "ms": round((end - start) * 1000, 1), **extra})

    def add_search(self, i: int, trace: dict):
        for s in trace.pop("spans", []):
            self.spans.append({"key": s["key"], "label": SPAN_LABELS.get(s["key"], s["key"]), "search": i,
                               "start": round((s["start"] - self.t0) * 1000, 1), "ms": s["ms"]})
        self.searches.append(trace)

    def finish(self, hits: list[dict], best: float | None, no_answer: bool, prompt: dict | None,
               fusion: dict | None = None) -> dict:
        ids = [h["chunk_id"] for h in hits]
        for s in self.searches:
            ids += [x["chunk_id"] for x in s["dense"] + s["bm25"] + s["fused"]]
        labels = {}
        for cid, m in chunk_meta(ids).items():
            labels[cid] = {"doc": short_doc(m.get("doc_title", "")), "art": m.get("article_number") or "",
                           "title": (m.get("article_title") or "")[:90], "status": m.get("status"),
                           "type": m.get("doc_type")}
        d = self.d
        d["searches"] = self.searches
        d["fusion"] = fusion
        d["labels"] = labels
        d["final"] = [{"n": i, "chunk_id": h["chunk_id"], "score": h.get("score"), "cosine": h.get("cosine"),
                       "rank_dense": h.get("rank_dense"), "rank_bm25": h.get("rank_bm25")} for i, h in enumerate(hits, 1)]
        d["threshold"] = {"no_answer_cos": NO_ANSWER_COS, "best_cos": best, "no_answer": no_answer}
        if prompt:
            ts, tok = _tokens(prompt["system"])
            tu, _ = _tokens(prompt["user"])
            d["prompt"] = {**prompt, "tokens": {"system": ts, "user": tu, "total": ts + tu, "method": tok},
                           "chars": len(prompt["system"]) + len(prompt["user"])}
        else:
            d["prompt"] = None
        d["timeline"] = sorted(self.spans, key=lambda s: s["start"])
        d["total_ms"] = round((time.perf_counter() - self.t0) * 1000, 1)
        d["_t0"] = self.t0  # app.py LLM vaqtlarini shu nuqtaga nisbatan hisoblaydi (javobga chiqmaydi)
        return d


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
                  llm_plan: bool = False, xray: bool = False, **kw) -> Iterator[tuple[str, dict]]:
    """Bosqichlar + natija. chunk_ids berilsa (sodda rejim) qayta qidirilmaydi: o'sha manbalar, o'sha [n].
    xray=True: natijada "xray" - qidiruv ichi (XRay); qo'shimcha LLM so'rovisiz, faqat so'ralganda hisoblanadi."""
    question = question.strip()
    lang = resolve_lang(question, lang_pref)
    # LLM'ga beriladigan savol: o'zbekcha kirill -> lotin (lotinda javob yozishi uchun), ruscha - asl holida
    q_llm = question if lang == "ru" else prepare_query(question)
    steps: list[dict] = []
    xr = XRay(question, lang, lang_pref, mode) if xray else None

    def done(ev):
        steps.append(ev[1])
        return ev

    if chunk_ids:
        t = time.time()
        tp = time.perf_counter()
        yield _step("reuse", "Manbalar qayta ishlatilmoqda", "run")
        hits = get_chunks(chunk_ids)
        if xr:
            xr.span("reuse", tp)
            xr.d["analysis"]["reuse"] = True
        yield done(_step("reuse", "Manbalar qayta ishlatilmoqda", "done",
                         f"qayta qidiruvsiz · {len(hits)} ta modda", int((time.time() - t) * 1000)))
        user = f"MANBALAR:\n\n{format_context(hits)}\n\n===\n\nSAVOL: {q_llm}"
        if base_answer:
            base = cyr_to_lat(base_answer) if re.search(r"[ЎўҚқҒғҲҳ]", base_answer) else base_answer
            user += f"\n\nYURIDIK JAVOB (shuni soddaroq tushuntir, [n] lar yuqoridagi manbalarga tegishli):\n{base[:6000]}"
        prompt = {"system": system_prompt(lang, mode), "user": user} if hits else None
        yield "result", {"sources": source_cards(hits), "no_answer": not hits, "best_cosine": None, "lang": lang,
                         "parts": [], "steps": steps, "prompt": prompt,
                         **({"xray": xr.finish(hits, None, not hits, prompt)} if xr else {})}
        return

    # 1. tahlil
    t = time.time()
    tp = time.perf_counter()
    yield _step("analyze", "Savol tahlil qilinmoqda", "run")
    use_llm_plan = llm_plan and plan.llm_enabled()
    parts = plan.llm_split(question) if use_llm_plan else plan.split_question(question)
    detail = f"Javob tili: {LANG_NAMES[lang]}"
    if parts:
        detail += f" · {len(parts)} qismga boʻlindi"
    if xr:
        xr.span("analyze", tp)
        xr.d["analysis"].update(parts=parts, planner="llm" if use_llm_plan else "evristika")
    yield done(_step("analyze", "Savol tahlil qilinmoqda", "done", detail, int((time.time() - t) * 1000)))

    # 2. qidiruv (to'liq savol + har qism alohida)
    lists = []
    queries = [question] + parts
    for i, q in enumerate(queries):
        t = time.time()
        label = "Qidirilmoqda" if i == 0 else f"Qidirilmoqda: «{q if len(q) <= 46 else q[:44].rstrip() + '…'}»"
        yield _step(f"search{i}", label, "run")
        trace: dict | None = {} if xr else None
        res = hybrid_search(q, k=k, lang=lang, trace=trace, **kw)
        if xr:
            xr.add_search(i, trace)
        lists.append(res)
        docs = []
        for h in res:
            d = short_doc(h.get("doc_title", ""))
            if d not in docs:
                docs.append(d)
        yield done(_step(f"search{i}", label, "done", " · ".join(docs[:2]) + (f" · +{len(docs) - 2}" if len(docs) > 2 else ""),
                         int((time.time() - t) * 1000)))

    # 3. birlashtirish
    t = time.time()
    tp = time.perf_counter()
    fusion = None
    if parts:
        before = sum(len(x) for x in lists)
        hits = _fuse(lists, max(k, K_SPLIT))
        found_detail = f"{len(queries)} qidiruv birlashtirildi, {before - len(hits)} ta takror olib tashlandi"
        if xr:
            xr.span("fuse", tp)
            fusion = {"method": "RRF (har qidiruv og'irligi 1, har qismning eng yaxshi 2 tasi albatta kiradi)",
                      "rrf_k": RRF_K, "before": before, "after": len(hits),
                      "from": {h["chunk_id"]: [i for i, lst in enumerate(lists) if any(x["chunk_id"] == h["chunk_id"] for x in lst)]
                               for h in hits}}
    else:
        hits = lists[0]
        n_docs = len({h.get("doc_id") or h.get("doc_title") for h in hits})
        found_detail = f"{n_docs} ta hujjatdan"
    yield done(_step("found", f"{len(hits)} ta modda topildi", "done", found_detail, int((time.time() - t) * 1000)))

    # 4. tekshiruv: eng yaqin moddaning o'xshashligi, holati
    t = time.time()
    tp = time.perf_counter()
    yield _step("check", "Tekshirilmoqda", "run")
    best = max((h.get("cosine") or 0) for h in hits) if hits else 0
    no_answer = not hits or best < NO_ANSWER_COS
    active = sum(1 for h in hits if h.get("status") == "amalda")
    if no_answer:
        check_detail = "mos modda yoʻq — taxmin qilinmaydi"
    else:
        check_detail = (f"eng yaqin moslik {round(best * 100)}% · "
                        + ("hammasi amaldagi tahrir" if active == len(hits) else f"{active} tasi amalda"))
    if xr:
        xr.span("check", tp)
    yield done(_step("check", "Tekshirilmoqda", "done", check_detail, int((time.time() - t) * 1000)))

    if no_answer:
        yield "result", {"sources": source_cards(hits[:3]), "no_answer": True, "best_cosine": best, "lang": lang,
                         "parts": parts, "steps": steps, "prompt": None,
                         **({"xray": xr.finish(hits, best, True, None, fusion)} if xr else {})}
        return
    user = f"MANBALAR:\n\n{format_context(hits)}\n\n===\n\nSAVOL: {q_llm}"
    if parts:
        user += "\n\nSavol bir necha qismdan iborat, har biriga alohida javob ber:\n" + \
                "\n".join(f"{i}) {p if lang == 'ru' else prepare_query(p)}" for i, p in enumerate(parts, 1))
    prompt = {"system": system_prompt(lang, mode), "user": user}
    yield "result", {"sources": source_cards(hits), "no_answer": False, "best_cosine": best, "lang": lang,
                     "parts": parts, "steps": steps, "prompt": prompt,
                     **({"xray": xr.finish(hits, best, False, prompt, fusion)} if xr else {})}


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
