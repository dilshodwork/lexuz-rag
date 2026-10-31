"""Dalil veb-ilovasi: FastAPI backend + web/dist dagi frontend.

Ishga tushirish (loyiha papkasidan):
    .venv/bin/python -m uvicorn lexrag.web.app:app --port 8000

API:
    POST /api/ask      SSE oqim: sources -> delta ... -> done (yoki error)
    GET  /api/search   faqat qidiruv (LLM'siz)
    GET  /api/health   server, indeks va LLM holati (kalitning o'zi qaytarilmaydi)
    GET  /api/stats    baza statistikasi (report.md va indeksdan)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from .. import config, llm, rag
from ..retrieval import MODEL, _bm25, prepare_query
from ..indexer import embed_query, get_collection

log = logging.getLogger("lexrag.web")
DIST = config.ROOT / "web" / "dist"
DOC_TYPES = ["Qonun", "Kodeks", "Konstitutsiya"]
STATE: dict = {"ready": False, "error": None, "count": None}
# ONNX va ChromaDB bir vaqtda bitta qidiruvni bajaradi (CPU baribir band)
_search_lock = threading.Lock()


def _warmup():
    t0 = time.time()
    try:
        embed_query(MODEL, "salom")      # bge-m3 ONNX modeli xotiraga
        _bm25()                          # BM25 indeksi
        STATE["count"] = get_collection(MODEL, create=False).count()
        STATE["ready"] = True
        log.info("Model va indeks yuklandi: %.1fs, %s chunk", time.time() - t0, STATE["count"])
    except Exception as e:  # noqa: BLE001 - server ishlayveradi, /api/health xatoni ko'rsatadi
        STATE["error"] = str(e)
        log.exception("Indeksni yuklab bo'lmadi")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    await run_in_threadpool(_warmup)
    yield


app = FastAPI(title="Dalil", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


# ---------------------------------------------------------------- yordamchilar
class Filters(BaseModel):
    only_active: bool = True
    include_amending: bool = False
    doc_types: list[str] = Field(default_factory=lambda: list(DOC_TYPES))


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    filters: Filters = Field(default_factory=Filters)
    k: int = Field(default=rag.K_CONTEXT, ge=1, le=12)


def _search_kw(f: Filters) -> dict:
    types = [t for t in f.doc_types if t in DOC_TYPES]
    return {"only_active": f.only_active, "no_amending": not f.include_amending,
            "doc_types": None if not types or len(types) == len(DOC_TYPES) else types}


def _llm_info() -> dict:
    try:
        provider, model, _ = llm.settings()
        return {"configured": True, "provider": provider, "model": model}
    except RuntimeError:
        return {"configured": False, "provider": None, "model": None}


def _human_error(e: BaseException) -> tuple[str, str]:
    """(kod, foydalanuvchiga ko'rinadigan matn). Asl xato faqat server logiga yoziladi."""
    msg = str(e)
    if isinstance(e, RuntimeError) and ("sozlanmagan" in msg or ".env da yo'q" in msg):
        return "no_key", ("LLM uchun API kalit sozlanmagan. Loyiha papkasidagi .env fayliga "
                          "GEMINI_API_KEY=... qatorini yozing va serverni qayta ishga tushiring. "
                          "Manbalar qidiruvi kalitsiz ham ishlaydi.")
    if isinstance(e, httpx.TimeoutException):
        return "timeout", "LLM javob berishga ulgurmadi (vaqt tugadi). Birozdan keyin qayta urinib koʻring."
    if isinstance(e, httpx.TransportError):
        return "network", "LLM serveriga ulanib boʻlmadi. Internet aloqasini tekshirib, qayta urinib koʻring."
    if isinstance(e, llm.LLMBusy):
        return "busy", "LLM hozir band (soʻrovlar koʻp). Bir daqiqadan keyin qayta urinib koʻring."
    if "API_KEY_INVALID" in msg or "xatosi 401" in msg or "xatosi 403" in msg:
        return "bad_key", "API kalit notoʻgʻri yoki muddati oʻtgan. .env dagi kalitni tekshiring."
    if "xatosi 404" in msg:
        return "llm", "Tanlangan LLM modeli topilmadi. .env dagi LLM_MODEL ni tekshiring yoki boʻsh qoldiring."
    if "xatosi" in msg:
        return "llm", "LLM xizmati xato qaytardi. Birozdan keyin qayta urinib koʻring."
    return "server", "Serverda kutilmagan xato yuz berdi. Qayta urinib koʻring."


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# LLM manbalarda javob topmasa shu iborani yozadi (rag.SYSTEM, 4-qoida)
NOT_FOUND_RE = re.compile(r"^\W*Bazadagi hujjatlarda bu savolga[^.]*topilmadi", re.I)


# ---------------------------------------------------------------- API
@app.post("/api/ask")
async def ask(body: AskBody):
    question = body.question.strip()

    async def events() -> AsyncIterator[str]:
        t0 = time.time()
        if not STATE["ready"]:
            yield _sse("error", {"code": "index", "message": "Qidiruv indeksi yuklanmagan. Server logini tekshiring."})
            return
        try:
            def _prep():
                with _search_lock:
                    return rag.prepare(question, k=body.k, **_search_kw(body.filters))
            p = await run_in_threadpool(_prep)
        except Exception as e:  # noqa: BLE001
            log.exception("qidiruv xatosi")
            code, text = _human_error(e)
            yield _sse("error", {"code": code, "message": text})
            return
        yield _sse("sources", {"sources": p["sources"], "no_answer": p["no_answer"],
                               "query_latin": prepare_query(question),
                               "search_ms": int((time.time() - t0) * 1000)})
        if p["no_answer"]:
            yield _sse("delta", {"text": rag.NO_ANSWER_TEXT})
            yield _sse("done", {"no_answer": True, "model": None, "ms": int((time.time() - t0) * 1000)})
            return
        parts: list[str] = []
        try:
            async for piece in iterate_in_threadpool(llm.stream(rag.SYSTEM, p["user"])):
                parts.append(piece)
                yield _sse("delta", {"text": piece})
        except asyncio.CancelledError:  # foydalanuvchi to'xtatdi / sahifani yopdi
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("LLM xatosi: %s", str(e)[:300])
            code, text = _human_error(e)
            yield _sse("error", {"code": code, "message": text, "partial": bool(parts)})
            return
        text = "".join(parts)
        yield _sse("done", {"no_answer": bool(NOT_FOUND_RE.search(text)), "model": llm.LAST_MODEL or _llm_info()["model"],
                            "ms": int((time.time() - t0) * 1000)})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/search")
async def search(q: str = Query(min_length=1, max_length=1000), k: int = Query(8, ge=1, le=30),
                 only_active: bool = True, include_amending: bool = False,
                 types: str = Query("", description="vergul bilan: Qonun,Kodeks,Konstitutsiya")):
    if not STATE["ready"]:
        return JSONResponse({"error": "Qidiruv indeksi yuklanmagan."}, status_code=503)
    f = Filters(only_active=only_active, include_amending=include_amending,
                doc_types=[t.strip() for t in types.split(",") if t.strip()] or list(DOC_TYPES))
    t0 = time.time()

    def _run():
        with _search_lock:
            return rag.source_cards(rag.retrieve(q, k=k, **_search_kw(f)))
    try:
        results = await run_in_threadpool(_run)
    except Exception as e:  # noqa: BLE001
        log.exception("qidiruv xatosi")
        return JSONResponse({"error": _human_error(e)[1]}, status_code=500)
    return {"query": q, "query_latin": prepare_query(q), "took_ms": int((time.time() - t0) * 1000),
            "results": results}


@app.get("/api/health")
async def health():
    return {"ok": STATE["ready"], "index_ready": STATE["ready"], "index_error": STATE["error"],
            "chunks": STATE["count"], "embedding_model": MODEL, "llm": _llm_info()}


@lru_cache(maxsize=1)
def _report_stats() -> dict:
    """report.md dagi raqamlar (qayta hisoblamaslik uchun)."""
    out: dict = {"documents": None, "by_type": {}, "by_status": {}, "chunks": None, "report_date": None}
    try:
        t = config.REPORT.read_text(encoding="utf-8")
    except OSError:
        return out
    num = lambda s: int(s.replace(",", "").replace(" ", ""))  # noqa: E731
    if m := re.search(r"Jami: saytda / ro'yxatda \| (\d[\d,]*)", t):
        out["documents"] = num(m.group(1))
    if m := re.search(r"Turi: (.+)", t):
        out["by_type"] = {k.strip(): num(v) for k, v in re.findall(r"([^:,]+): (\d[\d,]*)", m.group(1))}
    if m := re.search(r"Holati: (.+)", t):
        out["by_status"] = {k.strip(): num(v) for k, v in re.findall(r"([^:,]+): (\d[\d,]*)", m.group(1))}
    if m := re.search(r"Chunklar soni \| (\d[\d,]*)", t):
        out["chunks"] = num(m.group(1))
    if m := re.search(r"Yaratilgan: (\d{4})-(\d{2})-(\d{2})", t):
        out["report_date"] = f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return out


@app.get("/api/stats")
async def stats():
    r = _report_stats()
    return {"documents": r["documents"], "chunks": STATE["count"] or r["chunks"], "by_type": r["by_type"],
            "by_status": r["by_status"], "base_date": r["report_date"], "source": "lex.uz",
            "embedding_model": MODEL}


@app.get("/api/{rest:path}", include_in_schema=False)
async def api_404(rest: str):
    return JSONResponse({"error": f"Bunday API yoʻq: /api/{rest}"}, status_code=404)


# ---------------------------------------------------------------- frontend (web/dist)
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    f = (DIST / path).resolve()
    if path and f.is_file() and DIST.resolve() in f.parents:
        return FileResponse(f)
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<h1>Frontend yig'ilmagan</h1><p>Avval: <code>cd web &amp;&amp; npm install &amp;&amp; "
                        "npm run build</code>, keyin serverni qayta ishga tushiring.</p>", status_code=503)
