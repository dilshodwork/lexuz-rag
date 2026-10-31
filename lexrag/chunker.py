"""Tozalangan hujjatlarni RAG uchun chunklarga bo'lish.

Qoidalar:
* Asosiy birlik - bitta modda. Modda hech qachon boshqa modda bilan aralashmaydi
  (faqat --merge-short berilsa, bir bob ichidagi qisqa moddalar birlashtiriladi).
* Modda CHUNK_MAX_TOKENS dan uzun bo'lsa, qismlari/bandlari (xatboshilar) bo'yicha bo'linadi,
  bo'laklar hajmi tenglashtiriladi va har yangi bo'lak oldingisining oxiridan ~80 token overlap oladi.
  Bitta xatboshi o'zi juda uzun bo'lsa - gaplar bo'yicha bo'linadi.
* Moddadan oldingi matn (preambula) va moddasiz hujjatlar bo'lim/bob yo'li bo'yicha guruhlanadi.
* Har chunk boshida kontekst sarlavhasi: "<Hujjat nomi> > <Bo'lim> > <Bob> > N-modda. Sarlavha".
* Token soni BAAI/bge-m3 tokenizatori bilan sanaladi (embedding modeli bilan bir xil).
"""
from __future__ import annotations

import json
import logging
import math
import re
from functools import lru_cache

from tqdm import tqdm

from . import config
from .parser import heading_level

log = logging.getLogger(__name__)

SENT_RE = re.compile(r"(?<=[.;:!?])\s+(?=[A-ZÀ-ÝʻʼА-Я0-9“«(])")


@lru_cache(maxsize=1)
def _tokenizer():
    from tokenizers import Tokenizer
    return Tokenizer.from_pretrained(config.TOKENIZER_NAME)


def ntok(text: str) -> int:
    if not text:
        return 0
    return len(_tokenizer().encode(text, add_special_tokens=False).ids)


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def doc_label(doc: dict) -> str:
    title = doc.get("title") or ""
    extra = ", ".join(x for x in [doc.get("doc_type"), doc.get("number"), _fmt_date(doc.get("adoption_date"))] if x)
    return f"{title} ({extra})" if extra else title


def split_path(path: list[str]) -> dict:
    out = {"annex": None, "part": None, "section": None, "chapter": None, "paragraph": None}
    for h in path:
        lvl, kind = heading_level(h)
        key = {"ilova": "annex", "qism": "part", "bolim": "section", "bob": "chapter",
               "paragraf": "paragraph"}.get(kind, "chapter")
        out[key] = h
    return out


def _split_long_para(p: str, limit: int) -> list[str]:
    """Juda uzun xatboshini gaplar bo'yicha (kerak bo'lsa so'zlar bo'yicha) bo'lish."""
    sents = SENT_RE.split(p)
    pieces, cur = [], ""
    for s in sents:
        if ntok(s) > limit:  # gapning o'zi ham uzun - so'zlar bo'yicha
            words, buf = s.split(), []
            for w in words:
                buf.append(w)
                if ntok(" ".join(buf)) > limit:
                    buf.pop()
                    pieces.append(" ".join(buf))
                    buf = [w]
            s = " ".join(buf)
        cand = (cur + " " + s).strip()
        if cur and ntok(cand) > limit:
            pieces.append(cur)
            cur = s
        else:
            cur = cand
    if cur:
        pieces.append(cur)
    return pieces


def _tail_overlap(paras: list[str], max_tok: int) -> list[str]:
    """Oldingi bo'lak oxiridan overlap: oxirgi xatboshi (yoki uning oxirgi gaplari)."""
    if not paras or max_tok <= 0:
        return []
    last = paras[-1]
    if ntok(last) <= max_tok:
        return [last]
    sents = SENT_RE.split(last)
    out = []
    for s in reversed(sents):
        if ntok(" ".join([s] + out)) > max_tok:
            break
        out.insert(0, s)
    if not out:  # bitta uzun gap - oxirgi so'zlardan overlap
        words = last.split()
        lo = max(0, len(words) - max_tok)
        while lo < len(words) and ntok(" ".join(words[lo:])) > max_tok:
            lo += 5
        out = ["… " + " ".join(words[lo:])] if lo < len(words) else []
    return [" ".join(out)] if out else []


def pack_paragraphs(paras: list[str], budget: int, overlap: int) -> list[list[str]]:
    pieces = []
    for p in paras:
        pieces.extend(_split_long_para(p, budget) if ntok(p) > budget else [p])
    total = sum(ntok(p) for p in pieces)
    if total <= budget:
        return [pieces]
    n = math.ceil(total / budget)
    target = min(budget, math.ceil(total / n) + overlap)  # bo'laklarni tenglashtirish
    groups, cur, cur_t = [], [], 0
    for p in pieces:
        t = ntok(p)
        if cur and cur_t + t > target:
            groups.append(cur)
            ov = _tail_overlap(cur, overlap)
            cur = ov[:] if sum(ntok(x) for x in ov) + t <= budget else []
            cur_t = sum(ntok(x) for x in cur)
        cur.append(p)
        cur_t += t
    if cur:
        groups.append(cur)
    return groups


def doc_units(doc: dict) -> list[dict]:
    """Hujjatni birliklarga ajratish: modda yoki (preambula/moddasiz) matn guruhi."""
    units, buf = [], None
    for b in doc["structure"]:
        if b["kind"] == "article":
            if buf:
                units.append(buf)
                buf = None
            units.append({"type": "article", "number": b["number"], "title": b["title"],
                          "path": b["path"], "anchor": b["anchor"], "paras": b["paras"],
                          "amendments": b.get("amendments", [])})
        elif b["kind"] == "para":
            if buf is None or buf["path"] != b["path"]:
                if buf:
                    units.append(buf)
                buf = {"type": "preamble" if not b["path"] and not units else "text", "number": None,
                       "title": None, "path": b["path"], "anchor": b["anchor"], "paras": [], "amendments": []}
            buf["paras"].append(b["text"])
        else:  # heading
            if buf:
                units.append(buf)
                buf = None
    if buf:
        units.append(buf)
    return units


def unit_heading(doc: dict, u: dict) -> str:
    parts = [doc_label(doc)] + list(u["path"])
    if u["type"] == "article":
        parts.append(f"{u['number']}-modda. {u['title']}".strip() if u["title"] else f"{u['number']}-modda")
    elif u["type"] == "preamble":
        parts.append("Preambula")
    return " > ".join(parts)


def make_chunks(doc: dict, merge_short: bool = False) -> list[dict]:
    max_tok, overlap = config.CHUNK_MAX_TOKENS, config.CHUNK_OVERLAP_TOKENS
    units = [u for u in doc_units(doc) if u["paras"] or u["title"]]
    if merge_short:
        units = _merge_short_units(doc, units)
    out = []
    base_meta = {
        "doc_id": doc["id"], "lex_id": doc["lex_id"], "doc_title": doc["title"], "doc_type": doc["doc_type"],
        "doc_number": doc["number"], "adoption_date": doc["adoption_date"], "issuing_body": doc["issuing_body"],
        "status": doc["status"], "last_edition_date": doc["last_edition_date"], "language": doc["language"],
        "is_amending_law": doc.get("is_amending_law", False),
        "collection": doc.get("collection", "qonun"),
        "doc_url": doc["url"],
    }
    for ui, u in enumerate(units):
        heading = unit_heading(doc, u)
        budget = max(150, max_tok - ntok(heading) - 12)
        paras = u["paras"] or [u["title"]]
        groups = pack_paragraphs(paras, budget, overlap)
        sp = split_path(u["path"])
        anchor = u.get("anchor")
        for gi, g in enumerate(groups):
            h = heading if len(groups) == 1 else f"{heading} [{gi + 1}/{len(groups)}-bo'lak]"
            body = "\n".join(g)
            text = f"{h}\n\n{body}"
            # unit tartib raqami ham kiradi: ilovadagi "1-modda" asosiy qonundagi 1-modda bilan to'qnashmaydi
            cid = f"{doc['id']}_{ui:04d}_{u['number'] or u['type']}_{gi + 1}"
            out.append({
                "chunk_id": cid,
                **base_meta,
                "unit_type": u["type"],
                "article_number": u["number"] if u["type"] == "article" else None,
                "article_numbers": u.get("numbers") or ([u["number"]] if u["number"] else []),
                "article_title": u["title"],
                "annex": sp["annex"], "part": sp["part"], "section": sp["section"], "chapter": sp["chapter"], "paragraph": sp["paragraph"],
                "heading": h,
                "chunk_index": gi + 1, "n_chunks_in_unit": len(groups),
                "source_url": f"{doc['url']}#{anchor}" if anchor else doc["url"],
                "amendments": u["amendments"],
                "text": text,
                "body": body,
                "n_tokens": ntok(text),
            })
    return out


def _merge_short_units(doc, units):
    """Bir xil bob ichidagi ketma-ket qisqa moddalarni ~CHUNK_TARGET_MIN tokengacha birlashtirish."""
    out, i = [], 0
    while i < len(units):
        u = dict(units[i])
        if u["type"] != "article":
            out.append(u)
            i += 1
            continue
        size = ntok("\n".join(u["paras"]))
        nums, j = [u["number"]], i + 1
        paras = [f"{u['number']}-modda. {u['title']}".strip()] + u["paras"]
        amends = list(u["amendments"])
        while size < config.CHUNK_TARGET_MIN and j < len(units):
            v = units[j]
            if v["type"] != "article" or v["path"] != u["path"]:
                break
            vt = ntok("\n".join(v["paras"]))
            if size + vt > config.CHUNK_MAX_TOKENS - 120:
                break
            paras += [f"{v['number']}-modda. {v['title']}".strip()] + v["paras"]
            amends += v["amendments"]
            nums.append(v["number"])
            size += vt
            j += 1
        if len(nums) > 1:
            u.update({"number": f"{nums[0]}–{nums[-1]}", "numbers": nums, "title": "", "paras": paras,
                      "amendments": amends})
        out.append(u)
        i = j
    return out


def chunk_all(merge_short: bool = False) -> dict:
    files = sorted(config.CLEAN.glob("*.json"))
    n, seen, dup = 0, set(), 0
    with open(config.CHUNKS, "w", encoding="utf-8") as f:
        for p in tqdm(files, desc="chunk"):
            doc = json.loads(p.read_text(encoding="utf-8"))
            for c in make_chunks(doc, merge_short=merge_short):
                if c["chunk_id"] in seen:  # bo'lmasligi kerak; bo'lsa ham indeksni buzmasin
                    dup += 1
                    c["chunk_id"] += f"_d{dup}"
                seen.add(c["chunk_id"])
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
                n += 1
    if dup:
        log.warning("%d ta takroriy chunk_id topildi va o'zgartirildi", dup)
    return {"documents": len(files), "chunks": n, "duplicate_ids": dup, "file": str(config.CHUNKS)}
