"""/v1 - test API ("RAG API — test spetsifikatsiyasi (lex.uz)", 03.11.2026).

Veb-chat (/api/ask, SSE) o'zgarmaydi; bu modul o'sha qidiruv va promptlar ustidagi alohida REST + JSON qatlam:

    POST /v1/rag/batch               1-10 savol -> javob, citations, contexts (sync; 110 s dan oshsa 202)
    GET  /v1/rag/batch/{batch_id}    saqlangan natija (processing | completed | failed)
    POST /v1/rag/query               bitta savol (debug)
    GET  /v1/meta                    model, embedding, indeks versiyasi, lex.uz snapshot sanasi
    GET  /v1/health                  servis holati

Sozlash (.env):
    RAG_API_KEYS=kalit1,kalit2       Authorization: Bearer <kalit>; bo'sh bo'lsa /v1/rag/* 401 qaytaradi
    V1_SYNC_WAIT_S=110               shundan keyin 202 (batch fonda davom etadi)

Qoidalar (spetsifikatsiya 2-5-bo'limlar):
* results[].id - items[].id bilan bir xil, har biri bir marta; savol xatosi batch'ni yiqitmaydi (status=error).
* citations[] faqat javobda [n] bilan keltirilgan va contexts[] da bor bo'laklardan; [n] = contexts[].rank.
* no_answer: eng yaqin modda juda uzoq (cosine < rag.NO_ANSWER_COS) bo'lsa LLM chaqirilmaydi; LLM o'zi
  "topilmadi" desa ham no_answer=true, citations=[].
* Idempotentlik: batch_id + so'rov xeshi sqlite'da (DALIL_DATA_DIR/state/v1_batches.sqlite, o'chirilmaydi).
  Shu batch_id boshqa mazmun bilan - 409. Saqlangan natijada retryable xatoli savollar bo'lsa, qayta
  yuborilganda faqat o'shalar qayta hisoblanadi.
* temperature (standart 0) va seed LLM'ga uzatiladi; qidiruv deterministik (bir xil savol - bir xil manbalar).
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from .. import config, llm, rag
from ..retrieval import MODEL, chunk_meta, prepare_query

log = logging.getLogger("lexrag.v1")
router = APIRouter(prefix="/v1")

PIPELINE_VERSION = "1.0.0"
TZ = timezone(timedelta(hours=5))  # Toshkent
LANG_IN = {"uz-Latn": "uz", "uz-Cyrl": "uz_cyr", "ru": "ru", "uz": "uz", "auto": None}
LANG_OUT = {"uz": "uz-Latn", "uz_cyr": "uz-Cyrl", "ru": "ru"}
DOC_TYPE_OUT = {"Qonun": "qonun", "Kodeks": "kodeks", "Konstitutsiya": "konstitutsiya"}
GEN_DEADLINE_S = 90     # bitta savol generatsiyasi shundan oshsa - LLM_TIMEOUT


def _sync_wait() -> float:
    try:
        return float(os.environ.get("V1_SYNC_WAIT_S", "110"))
    except ValueError:
        return 110.0


class JSONUTF8(JSONResponse):
    media_type = "application/json; charset=utf-8"


def _err(status: int, code: str, message: str, details: Any = None, headers: dict | None = None) -> JSONUTF8:
    body: dict = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONUTF8(body, status_code=status, headers=headers)


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


# ---------------------------------------------------------------- autentifikatsiya va rate limit
def _keys() -> list[str]:
    return [k.strip() for k in os.environ.get("RAG_API_KEYS", "").split(",") if k.strip()]


def _auth(request: Request) -> tuple[str | None, JSONUTF8 | None]:
    keys = _keys()
    h = request.headers.get("authorization", "")
    token = h[7:].strip() if h[:7].lower() == "bearer " else ""
    if not keys:
        return None, _err(401, "UNAUTHORIZED", "Serverda API kalit sozlanmagan (RAG_API_KEYS).")
    if not token:
        return None, _err(401, "UNAUTHORIZED", "Authorization: Bearer <API_KEY> sarlavhasi kerak.",
                          headers={"WWW-Authenticate": "Bearer"})
    for k in keys:
        if hmac.compare_digest(token.encode(), k.encode()):
            return hashlib.sha256(k.encode()).hexdigest()[:12], None
    return None, _err(403, "FORBIDDEN", "API kalit notoʻgʻri.")


class _Rate:
    """Kalit bo'yicha sirpanuvchi oyna: 1 soniyada `per_s` tagacha so'rov (spetsifikatsiya: kamida 1 batch/s)."""

    def __init__(self, per_s: int):
        self.per_s = per_s
        self.hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 1.0:
                q.popleft()
            if len(q) >= self.per_s:
                return False
            q.append(now)
            return True


_rate_post = _Rate(5)
_rate_get = _Rate(20)


def _guard(request: Request, rate: _Rate) -> tuple[str | None, JSONUTF8 | None]:
    who, bad = _auth(request)
    if bad:
        return None, bad
    if not rate.check(who):
        return None, _err(429, "RATE_LIMITED", "Juda koʻp soʻrov. Retry-After dan keyin qayta yuboring.",
                          headers={"Retry-After": "1"})
    return who, None


# ---------------------------------------------------------------- so'rov modeli
class Options(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    return_contexts: bool = True
    return_debug: bool = False
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int | None = None
    as_of_date: date | None = None
    answer_language: str = "auto"

    @field_validator("answer_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in ("auto", "uz-Latn", "uz-Cyrl", "ru"):
            raise ValueError("auto | uz-Latn | uz-Cyrl | ru")
        return v


class Item(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    language: str | None = None

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question boʻsh")
        return v


class BatchReq(BaseModel):
    run_id: str = Field(min_length=1, max_length=200)
    batch_id: str = Field(min_length=1, max_length=200)
    batch_index: int = Field(ge=1)
    total_batches: int = Field(ge=1)
    options: Options = Field(default_factory=Options)
    items: list[Item] = Field(min_length=1, max_length=10)


class QueryReq(BaseModel):
    id: str = Field(default="q", min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=2000)
    language: str | None = None
    options: Options = Field(default_factory=Options)


def _validation_details(e: ValidationError) -> list[dict]:
    return [{"loc": ".".join(str(x) for x in d["loc"]), "msg": d["msg"]} for d in e.errors()]


async def _body(request: Request, model):
    try:
        raw = await request.body()
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, _err(400, "VALIDATION_ERROR", "Soʻrov tanasi toʻgʻri UTF-8 JSON emas.")
    if not isinstance(data, dict):
        return None, _err(400, "VALIDATION_ERROR", "Soʻrov tanasi JSON obyekt boʻlishi kerak.")
    try:
        return model.model_validate(data), None
    except ValidationError as e:
        return None, _err(400, "VALIDATION_ERROR", "Soʻrov spetsifikatsiyaga mos emas.", _validation_details(e))


# ---------------------------------------------------------------- tizim versiyalari
_SYSTEM_CACHE: dict = {}


def _snapshot_date() -> str | None:
    try:
        t = config.REPORT.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"Yaratilgan: (\d{4}-\d{2}-\d{2})", t)
    return m.group(1) if m else None


def _index_version() -> str | None:
    """Indeks tarkibidan (chunk id ro'yxati) - qayta qurilgandagina o'zgaradi. Fayl sanasi yaramaydi:
    ChromaDB sqlite'ni ochganda mtime yangilanadi."""
    if v := os.environ.get("INDEX_VERSION", "").strip():
        return v
    p = config.INDEX_DIR / "bm25" / "ids.json"
    try:
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:8]
    except OSError:
        return None
    return f"lex-idx-{_snapshot_date() or 'unknown'}-{h}"


def system_info() -> dict:
    if not _SYSTEM_CACHE:
        _SYSTEM_CACHE.update(index_version=_index_version(), lex_snapshot_date=_snapshot_date())
    try:
        provider, model, _ = llm.settings()
    except RuntimeError:
        provider, model = None, None
    return {"pipeline_version": PIPELINE_VERSION, "llm_provider": provider, "llm_model": model,
            "embedding_model": MODEL, "reranker": None, "retrieval": "hybrid: bge-m3 dense + BM25, RRF",
            "index_version": _SYSTEM_CACHE["index_version"],
            "lex_snapshot_date": _SYSTEM_CACHE["lex_snapshot_date"]}


# ---------------------------------------------------------------- iqtibos (quote) va qism
_WORD = re.compile(r"[0-9A-Za-zʻʼ'`ʼ‘’Ѐ-ӿ]+")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_REF = re.compile(r"\[(\d{1,2})\]")
_ITEM_LINE = re.compile(r"^\s*(\d+[\).]|[a-zа-я]\)|[—–\-•])")


def _norm_words(text: str) -> set[str]:
    t = text.lower().replace("ʼ", "'").replace("ʻ", "'").replace("‘", "'").replace("’", "'").replace("`", "'")
    return {w[:6] for w in _WORD.findall(t) if len(w) >= 3}


def _sentences(body: str) -> list[str]:
    out = []
    for para in body.split("\n"):
        for s in re.split(r"(?<=[.;!?])\s+", para.strip()):
            if len(s.strip()) >= 15:
                out.append(s.strip())
    return out or ([body.strip()[:500]] if body.strip() else [])


def _claims(answer: str, n: int) -> str:
    """Javobning [n] keltirilgan gaplari (quote tanlash uchun)."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", answer)
    return " ".join(p for p in parts if f"[{n}]" in p) or answer


def _quote(body: str, claim: str) -> str:
    """Manba matnidan aynan olingan gap: da'vo bilan eng ko'p so'z/raqam umumiy bo'lgani."""
    cw, cn = _norm_words(claim), set(_NUM.findall(claim))
    best, best_s = None, -1.0
    for i, s in enumerate(_sentences(body)):
        score = len(cw & _norm_words(s)) + 3 * len(cn & set(_NUM.findall(s))) - i * 0.01
        if score > best_s:
            best, best_s = s, score
    q = best or ""
    if len(q) > 500:
        cut = q[:500]
        q = cut[: cut.rfind(" ")] if " " in cut else cut
    return q


def _part(body: str, quote: str, whole_article: bool) -> str | None:
    """Moddaning qismi (xatboshi): band/kichik bandlar ("1)", "a)", "—") qism hisoblanmaydi.
    Uzun modda bir necha bo'lakka bo'lingan bo'lsa, bo'lak ichidan qism raqamini aniqlab bo'lmaydi - None."""
    if not whole_article or not quote:
        return None
    n = 0
    for para in (p for p in body.split("\n") if p.strip()):
        if not _ITEM_LINE.match(para) or n == 0:
            n += 1
        if quote[:60] in para:
            return f"{n}-qism"
    return None


# ---------------------------------------------------------------- bitta savol
class ItemError(Exception):
    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def _llm_error(e: BaseException) -> ItemError:
    msg = str(e)
    if isinstance(e, (httpx.TimeoutException, TimeoutError)):
        return ItemError("LLM_TIMEOUT", "LLM javob berishga ulgurmadi.", True)
    if isinstance(e, llm.LLMQuota):
        return ItemError("LLM_ERROR", "LLM kunlik kvotasi tugagan (429).", True)
    if isinstance(e, llm.LLMBusy):
        return ItemError("LLM_ERROR", "LLM vaqtincha band (429/503).", True)
    if isinstance(e, httpx.TransportError):
        return ItemError("LLM_ERROR", "LLM serveriga ulanib boʻlmadi.", True)
    if isinstance(e, RuntimeError) and ("sozlanmagan" in msg or ".env da yo'q" in msg):
        return ItemError("LLM_ERROR", "Serverda LLM sozlanmagan.", False)
    return ItemError("LLM_ERROR", "LLM xato qaytardi.", True)


def _prepare(question: str, k: int, lang_pref: str | None) -> dict:
    """rag.prepare_steps - har qadam veb-chat bilan umumiy qidiruv qulfi ostida."""
    from . import app as web
    gen = rag.prepare_steps(question, k=k, lang_pref=lang_pref, only_active=True, no_amending=True)
    result = None
    while True:
        with web._search_lock:
            try:
                ev, data = next(gen)
            except StopIteration:
                break
        if ev == "result":
            result = data
    if result is None:
        raise RuntimeError("qidiruv natija qaytarmadi")
    return result


def _context(card: dict, meta: dict, return_text: bool, used: bool) -> dict:
    art = card.get("article_number")
    c = {"rank": card["n"], "chunk_id": card["chunk_id"], "doc_id": f"lex:{meta.get('doc_id') or ''}",
         "doc_title": card.get("doc_title"), "article": f"{art}-modda" if art else None,
         "retrieval_score": round(card["cosine"], 4) if card.get("cosine") is not None else None,
         "fusion_score": card.get("score"), "rerank_score": None, "used_in_answer": used}
    if return_text:
        c["text"] = card.get("text")
    return c


def _citation(card: dict, meta: dict, answer: str) -> dict:
    art = card.get("article_number")
    quote = _quote(card.get("text") or "", _claims(answer, card["n"]))
    return {"ref": card["n"], "doc_id": f"lex:{meta.get('doc_id') or ''}", "doc_title": card.get("doc_title"),
            "doc_type": DOC_TYPE_OUT.get(card.get("doc_type"), (card.get("doc_type") or "").lower() or None),
            "doc_number": card.get("doc_number"),
            "url": card.get("doc_url"), "article_url": card.get("source_url"),
            "article": f"{art}-modda" if art else None, "article_title": card.get("article_title") or None,
            "part": _part(card.get("text") or "", quote, (meta.get("n_chunks_in_unit") or 1) == 1),
            "edition_date": card.get("last_edition_date"), "doc_status": card.get("status"),
            "chunk_id": card["chunk_id"], "quote": quote}


def run_item(item: Item, opt: Options) -> dict:
    t0 = time.perf_counter()
    base = {"id": item.id}
    if item.language is not None and item.language not in LANG_IN:
        return {**base, "status": "error", "answer": None, "answer_language": None, "no_answer": False,
                "confidence": None, "citations": [], "contexts": [],
                "error": {"code": "INVALID_LANGUAGE", "message": "language: uz-Latn | uz-Cyrl | ru",
                          "retryable": False}}
    # answer_language=auto - savol tilida: items[].language berilgan bo'lsa shu, bo'lmasa avtomatik
    pref = LANG_IN[opt.answer_language] if opt.answer_language != "auto" else LANG_IN.get(item.language or "auto")
    question = item.question.strip()
    timing = {"retrieval_ms": None, "rerank_ms": None, "generation_ms": None, "total_ms": None}
    try:
        try:
            p = _prepare(question, opt.top_k, pref)
        except Exception as e:  # noqa: BLE001
            log.exception("v1 qidiruv xatosi (%s)", item.id)
            raise ItemError("RETRIEVAL_FAILED", f"Qidiruv xatosi: {type(e).__name__}", True) from e
        t_ret = time.perf_counter()
        timing["retrieval_ms"] = int((t_ret - t0) * 1000)
        cards = p["sources"]
        metas = chunk_meta([c["chunk_id"] for c in cards])
        answer, model, usage, llm_no = None, None, None, False
        if p["no_answer"]:
            answer = rag.NO_ANSWER_TEXT
        else:
            out = rag.AnswerStream(p["lang"])
            text = ""
            try:
                for piece in llm.stream(p["prompt"]["system"], p["prompt"]["user"], temperature=opt.temperature,
                                        seed=opt.seed):
                    text += out.feed(piece)
                    if time.perf_counter() - t_ret > GEN_DEADLINE_S:
                        raise TimeoutError
                text += out.flush()
            except Exception as e:  # noqa: BLE001
                log.warning("v1 LLM xatosi (%s): %s", item.id, str(e)[:300])
                raise _llm_error(e) from e
            answer, llm_no = text.strip(), out.not_found()
            model = getattr(llm.LAST, "model", None)
            usage = getattr(llm.LAST, "usage", None) or None
            timing["generation_ms"] = int((time.perf_counter() - t_ret) * 1000)
        no_answer = bool(p["no_answer"] or llm_no)
        by_n = {c["n"]: c for c in cards}
        refs = [] if no_answer else list(dict.fromkeys(int(x) for x in _REF.findall(answer or "")))
        valid = [n for n in refs if n in by_n]
        if answer:  # [n] faqat citations'dagi manbaga: to'qilgan havola va no_answer'dagi havolalar olib tashlanadi
            answer = _REF.sub(lambda m: m.group(0) if not no_answer and int(m.group(1)) in by_n else "", answer)
            answer = re.sub(r" +([.,;:])", r"\1", answer).strip()
        citations = [_citation(by_n[n], metas.get(by_n[n]["chunk_id"], {}), answer) for n in valid]
        contexts = [_context(c, metas.get(c["chunk_id"], {}), opt.return_contexts, c["n"] in valid) for c in cards]
        best = p.get("best_cosine")
        res = {**base, "status": "no_answer" if no_answer else "ok", "answer": answer,
               "answer_language": LANG_OUT.get(p["lang"]), "no_answer": no_answer,
               "confidence": 0.0 if no_answer else (round(float(best), 3) if best is not None else None),
               "citations": citations, "contexts": contexts}
        if opt.return_debug:
            res["debug"] = {"rewritten_query": prepare_query(question), "sub_queries": p.get("parts") or [],
                            "retrieved_total": len(cards), "best_cosine": best,
                            "no_answer_threshold": rag.NO_ANSWER_COS,
                            "no_answer_reason": ("low_similarity" if p["no_answer"] else "llm_not_found" if llm_no
                                                 else None),
                            "llm_model": model,
                            "as_of_date_note": (None if opt.as_of_date is None else
                                                f"as_of_date qoʻllab-quvvatlanmaydi: indeksda faqat "
                                                f"{system_info()['lex_snapshot_date']} holatidagi amaldagi tahrir bor")}
        timing["total_ms"] = int((time.perf_counter() - t0) * 1000)
        res["timing"] = timing
        res["usage"] = usage
        res["error"] = None
        return res
    except ItemError as e:
        timing["total_ms"] = int((time.perf_counter() - t0) * 1000)
        return {**base, "status": "timeout" if e.code == "LLM_TIMEOUT" else "error", "answer": None,
                "answer_language": None, "no_answer": False, "confidence": None, "citations": [], "contexts": [],
                "timing": timing, "usage": None,
                "error": {"code": e.code, "message": e.message, "retryable": e.retryable}}


# ---------------------------------------------------------------- batch saqlash (idempotentlik)
class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, req_hash TEXT NOT NULL, "
                        "status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, response TEXT)")
        self.lock = threading.Lock()

    def get(self, batch_id: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT req_hash, status, response FROM batches WHERE batch_id=?",
                                (batch_id,)).fetchone()
        if not r:
            return None
        return {"req_hash": r[0], "status": r[1], "response": json.loads(r[2]) if r[2] else None}

    def put(self, batch_id: str, req_hash: str, status: str, response: dict | None):
        now = time.time()
        with self.lock:
            self.db.execute("INSERT INTO batches VALUES (?,?,?,?,?,?) ON CONFLICT(batch_id) DO UPDATE SET "
                            "status=excluded.status, updated=excluded.updated, response=excluded.response",
                            (batch_id, req_hash, status, now, now,
                             json.dumps(response, ensure_ascii=False) if response is not None else None))


_store: Store | None = None
_store_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}
_work_lock = threading.Lock()   # bir vaqtda bitta batch (CPU va LLM kvotasi)


def store() -> Store:
    global _store
    with _store_lock:
        if _store is None:
            _store = Store(config.STATE / "v1_batches.sqlite")
        return _store


def _req_hash(req: BatchReq) -> str:
    d = req.model_dump(mode="json")
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _summary(results: list[dict]) -> dict:
    s = {"total": len(results), "ok": 0, "no_answer": 0, "error": 0, "timeout": 0}
    for r in results:
        s[r["status"]] = s.get(r["status"], 0) + 1
    return s


def _process(req: BatchReq, h: str, previous: dict | None):
    """Fon oqimi: batch'ni hisoblab saqlaydi. previous - avvalgi natija (faqat retryable xatolar qayta)."""
    ev = _inflight[req.batch_id]
    received = _now()
    t0 = time.perf_counter()
    try:
        with _work_lock:
            old = {r["id"]: r for r in (previous or {}).get("results", [])}
            results = []
            for it in req.items:
                r = old.get(it.id)
                if r is None or (r["status"] in ("error", "timeout") and (r.get("error") or {}).get("retryable")):
                    r = run_item(it, req.options)
                results.append(r)
        resp = {"run_id": req.run_id, "batch_id": req.batch_id, "batch_index": req.batch_index,
                "total_batches": req.total_batches, "status": "completed", "system": system_info(),
                "options": req.options.model_dump(mode="json"),
                "timing": {"received_at": received, "completed_at": _now(),
                           "total_ms": int((time.perf_counter() - t0) * 1000)},
                "summary": _summary(results), "results": results}
        store().put(req.batch_id, h, "completed", resp)
    except Exception:  # noqa: BLE001
        log.exception("v1 batch %s yiqildi", req.batch_id)
        store().put(req.batch_id, h, "failed",
                    {"batch_id": req.batch_id, "run_id": req.run_id, "status": "failed",
                     "error": {"code": "INTERNAL", "message": "Batch qayta ishlashda xato.", "retryable": True}})
    finally:
        ev.set()
        _inflight.pop(req.batch_id, None)


def _stored_response(row: dict) -> JSONUTF8:
    if row["status"] == "completed":
        return JSONUTF8(row["response"])
    if row["status"] == "processing":
        return JSONUTF8({"batch_id": (row["response"] or {}).get("batch_id"), "status": "processing"},
                        status_code=202, headers={"Retry-After": "5"})
    return JSONUTF8(row["response"] or {"status": "failed"})


def _not_ready() -> JSONUTF8 | None:
    from . import app as web
    if web.STATE.get("ready"):
        return None
    if web.STATE.get("phase") == "error":
        return _err(503, "INDEX_UNAVAILABLE", "Qidiruv indeksi yuklanmadi.", headers={"Retry-After": "30"})
    return _err(503, "INDEX_UNAVAILABLE", "Server tayyorlanmoqda (indeks va model yuklanmoqda).",
                headers={"Retry-After": "10"})


# ---------------------------------------------------------------- endpointlar
@router.post("/rag/batch")
async def post_batch(request: Request):
    _, bad = _guard(request, _rate_post)
    if bad:
        return bad
    req, bad = await _body(request, BatchReq)
    if bad:
        return bad
    ids = [it.id for it in req.items]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        return _err(400, "VALIDATION_ERROR", "items[].id takrorlangan.", [{"loc": "items.id", "msg": ", ".join(dup)}])
    if req.batch_index > req.total_batches:
        return _err(400, "VALIDATION_ERROR", "batch_index total_batches dan katta.")
    h = _req_hash(req)
    st = store()
    with _store_lock:  # bir xil batch_id bilan parallel ikki so'rov ikki marta hisoblanmasin
        row = st.get(req.batch_id)
        if row and row["req_hash"] != h:
            return _err(409, "BATCH_ID_CONFLICT", "Bu batch_id boshqa mazmun bilan yuborilgan. Yangi batch_id bering.")
        ev = _inflight.get(req.batch_id)
        previous = None
        if ev is None:
            needs_retry = bool(row and row["status"] == "completed" and any(
                r["status"] in ("error", "timeout") and (r.get("error") or {}).get("retryable")
                for r in row["response"]["results"]))
            if row and row["status"] == "completed" and not needs_retry:
                return _stored_response(row)
            if nr := _not_ready():
                return nr
            previous = row["response"] if needs_retry else None
            ev = _inflight[req.batch_id] = threading.Event()
            st.put(req.batch_id, h, "processing", {"batch_id": req.batch_id, "status": "processing"})
            threading.Thread(target=_process, args=(req, h, previous), daemon=True,
                             name=f"v1-{req.batch_id[:40]}").start()
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(ev.wait, _sync_wait())
    return _stored_response(st.get(req.batch_id))


@router.get("/rag/batch/{batch_id}")
async def get_batch(batch_id: str, request: Request):
    _, bad = _guard(request, _rate_get)
    if bad:
        return bad
    row = store().get(batch_id)
    if not row:
        return _err(404, "NOT_FOUND", "Bunday batch_id yoʻq.")
    if row["status"] == "processing" and batch_id not in _inflight:
        # server qayta ishga tushgan: hisoblash yo'qolgan - qayta yuborish mumkin
        return JSONUTF8({"batch_id": batch_id, "status": "failed",
                         "error": {"code": "INTERNAL", "message": "Server qayta ishga tushdi, batch'ni qayta yuboring.",
                                   "retryable": True}})
    return _stored_response(row)


@router.post("/rag/query")
async def post_query(request: Request):
    _, bad = _guard(request, _rate_post)
    if bad:
        return bad
    req, bad = await _body(request, QueryReq)
    if bad:
        return bad
    if nr := _not_ready():
        return nr
    from starlette.concurrency import run_in_threadpool

    def work():
        with _work_lock:
            return run_item(Item(id=req.id, question=req.question, language=req.language), req.options)
    res = await run_in_threadpool(work)
    return JSONUTF8({"system": system_info(), "result": res})


@router.get("/meta")
async def meta():
    from . import app as web
    return JSONUTF8({**system_info(),
                     "index": {"chunks": web.STATE.get("count"), "chunking": "modda boʻyicha (1 modda = 1 chunk; "
                               "uzun moddalar overlap bilan boʻlinadi, maks 800 token)",
                               "statuses": "faqat amaldagi hujjatlar qidiriladi; kuchini yoʻqotganlar indeksda "
                                           "bor, doc_status bilan belgilangan",
                               "doc_id": "lex:<lex.uz hujjat raqami> (URL dagi raqam, minus belgisisiz)"},
                     "generation": {"temperature_default": 0, "seed": "Gemini/OpenAI ga uzatiladi",
                                    "no_answer_threshold_cosine": rag.NO_ANSWER_COS},
                     "limits": {"items_per_batch": 10, "question_max_chars": 2000, "top_k_max": 20,
                                "sync_wait_s": _sync_wait(), "rate_limit_per_s": _rate_post.per_s},
                     "languages": ["uz-Latn", "uz-Cyrl", "ru"], "as_of_date": "qoʻllab-quvvatlanmaydi"})


@router.get("/health")
async def health():
    from . import app as web
    status = "ready" if web.STATE.get("ready") else "error" if web.STATE.get("phase") == "error" else "loading"
    return JSONUTF8({"ok": bool(web.STATE.get("ready")), "status": status, "index_ready": bool(web.STATE.get("ready")),
                     "chunks": web.STATE.get("count"), "time": _now()},
                    status_code=200 if web.STATE.get("ready") else 503)
