"""RAG: savol -> gibrid qidiruv -> manbali kontekst -> LLM javobi (iqtiboslar bilan).

Qoidalar (system prompt):
* Faqat berilgan manbalar asosida javob; har bir da'vodan keyin [n] iqtibos.
* Manbalarda javob bo'lmasa - ochiq aytadi, o'zidan to'qimaydi.
* Eng yaqin manba juda uzoq bo'lsa (cosine < NO_ANSWER_COS), LLM chaqirilmaydi.
"""
from __future__ import annotations

from typing import Iterator

from . import llm
from .retrieval import hybrid_search, prepare_query

K_CONTEXT = 8
NO_ANSWER_COS = 0.45  # eval natijasiga qarab sozlanadi

SYSTEM = """Sen Oʻzbekiston Respublikasi qonunchiligi boʻyicha yordamchisan. Faqat oʻzbek tilida (lotin yozuvida) javob ber.

Qatʼiy qoidalar:
1. Faqat quyida berilgan MANBALAR matniga tayan. Oʻzingdan qoida, raqam, muddat yoki modda oʻylab topma.
2. Har bir daʼvodan keyin manba raqamini kvadrat qavsda yoz: [1], [2]. Bir nechta boʻlsa [1][3].
3. Javobda hujjat nomi va modda raqamini aniq ayt (masalan: "Mehnat kodeksining 217-moddasiga koʻra ...").
4. Agar manbalarda savolga javob boʻlmasa yoki yetarli boʻlmasa, shuni ochiq ayt: "Bazadagi hujjatlarda bu savolga aniq javob topilmadi." va qaysi yoʻnalishda qidirish mumkinligini qisqa ko'rsat. Taxmin qilma.
5. Javob tuzilishi: avval 1-2 gapda qisqa javob, keyin kerak boʻlsa tafsilotlar (roʻyxat boʻlishi mumkin). Ortiqcha kirish soʻzlari yozma.
6. Yuridik maslahat berayotganingni daʼvo qilma; sen qonun matnini tushuntirasan."""


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


def answer_stream(question: str, k: int = K_CONTEXT, **kw) -> tuple[list[dict], Iterator[str]]:
    hits = retrieve(question, k=k, **kw)
    best = max((h["cosine"] or 0) for h in hits) if hits else 0
    if not hits or best < NO_ANSWER_COS:
        def _none():
            yield ("Bazadagi hujjatlarda bu savolga mos qonun normasi topilmadi. "
                   "Savolni aniqroq yozib koʻring (masalan, qaysi soha yoki hujjat haqida).")
        return source_cards(hits[:3]), _none()
    q = prepare_query(question)
    user = f"MANBALAR:\n\n{format_context(hits)}\n\n===\n\nSAVOL: {q}"
    return source_cards(hits), llm.stream(SYSTEM, user)


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
