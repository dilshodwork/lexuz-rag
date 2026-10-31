"""Dalil veb-ilovasi: FastAPI backend + web/dist dagi frontend.

Ishga tushirish (loyiha papkasidan):
    .venv/bin/python -m uvicorn lexrag.web.app:app --port 8000

API:
    POST /api/ask      SSE oqim: step ... -> sources -> delta ... -> followups -> quota -> done (yoki error);
                       server kaliti, bepul limit
    POST /api/context  bosqichlar + manbalar + tayyor LLM so'rovi (system/user) + javobni qayta ishlash qoidasi:
                       brauzer o'z kaliti bilan LLM'ni o'zi chaqiradi
    POST /api/verify   javob ishonchliligi (har da'vo manbada asosi bormi), LLM'siz
    GET  /api/quota    bugungi bepul savollar (qancha qoldi)
    GET  /api/search   faqat qidiruv (LLM'siz)
    GET  /api/health   server, indeks va LLM holati (kalitning o'zi qaytarilmaydi)
    GET  /api/stats    baza statistikasi (report.md va indeksdan)
    GET  /api/eval     baholash natijalari (eval/results.json, sweep.json); POST /api/eval/run - fonda qayta hisoblash,
                       GET /api/eval/status - jarayon (EVAL_TOKEN bo'lsa X-Eval-Token sarlavhasi kerak)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import AsyncIterator, Literal

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from .. import config, llm, rag, trust
from . import quota
from ..lang import MARKER
from ..retrieval import MODEL, _bm25, prepare_query
from ..indexer import embed_query, get_collection

log = logging.getLogger("lexrag.web")
# DALIL_DIST: boshqa papkadagi frontend yig'masi (masalan, sinov serveri uchun)
DIST = Path(os.environ.get("DALIL_DIST") or config.ROOT / "web" / "dist")
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
    STATE["quota"] = quota.Quota()
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
    # "simple" - sodda tilda qayta javob: chunk_ids (o'sha manbalar, o'sha tartib) bilan, qayta qidiruvsiz
    mode: Literal["legal", "simple"] = "legal"
    chunk_ids: list[str] | None = Field(default=None, max_length=12)
    base_answer: str | None = Field(default=None, max_length=12000)
    # javob tili: auto - savol tilidan (lang.detect_lang)
    lang: Literal["auto", "uz", "uz_cyr", "ru"] = "auto"
    # LLM bilan savolni bo'lish (.env da LLM_PLAN=1 ham kerak); standart - LLM'siz evristika
    llm_plan: bool = False
    # X-ray: qidiruv ichi (dense/BM25/RRF ro'yxatlari, vaqtlar, prompt). Qo'shimcha LLM so'rovisiz; false - hisoblanmaydi
    xray: bool = False


class VerifyBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    chunk_ids: list[str] = Field(min_length=1, max_length=12)
    lang: Literal["uz", "uz_cyr", "ru"] = "uz"
    mode: Literal["legal", "simple"] = "legal"  # sodda javobdagi misol va maslahatlar tekshirilmaydi


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
        return "no_key", ("Serverda bepul AI sozlanmagan. Javob olish uchun oʻz AI kalitingizni ulang "
                          "(“AI ulash”, Gemini kaliti bepul). Server egasi boʻlsangiz: .env ga GEMINI_API_KEY=... "
                          "yozib, serverni qayta ishga tushiring. Manbalar qidiruvi kalitsiz ham ishlaydi.")
    if isinstance(e, httpx.TimeoutException):
        return "timeout", "LLM javob berishga ulgurmadi (vaqt tugadi). Birozdan keyin qayta urinib koʻring."
    if isinstance(e, httpx.TransportError):
        return "network", "LLM serveriga ulanib boʻlmadi. Internet aloqasini tekshirib, qayta urinib koʻring."
    if isinstance(e, llm.LLMQuota):
        return "quota", ("LLM'ning kunlik bepul limiti tugagan (Gemini bepul tarifi: har model uchun kuniga "
                         "20 ta soʻrov). Ertaga qayta urinib koʻring yoki .env ga boshqa API kalit yozing. "
                         "Manbalar yuqorida koʻrsatilgan.")
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


def _who(request: Request) -> list[tuple[str, int]]:
    return quota.identity(request.client.host if request.client else None, request.headers)[1]


def _quota_info(keys: list[tuple[str, int]]) -> dict:
    st = STATE["quota"].status(keys)
    return {**st, "free": _llm_info()["configured"] and quota.global_limit() > 0}


def _limit_message(st: dict) -> str:
    if st["reason"] == "global":
        return ("Bugungi umumiy bepul limit tugadi: server kaliti hammaga birgalikda kuniga "
                f"{quota.global_limit()} ta savolga yetadi. Oʻz AI kalitingizni ulang — Gemini kaliti bepul, "
                "2 daqiqada olinadi. Manbalar yuqorida koʻrsatilgan.")
    return (f"Bugungi {st['limit']} ta bepul savol tugadi. Davom etish uchun oʻz AI kalitingizni ulang — "
            "Gemini kaliti bepul, 2 daqiqada olinadi. Manbalar yuqorida koʻrsatilgan.")


def _steps_gen(body: AskBody):
    """rag.prepare_steps: har qadam qidiruv qulfi ostida (ONNX va ChromaDB bir vaqtda bitta so'rov)."""
    gen = rag.prepare_steps(body.question, k=body.k, lang_pref=None if body.lang == "auto" else body.lang,
                            mode=body.mode, chunk_ids=body.chunk_ids, base_answer=body.base_answer,
                            llm_plan=body.llm_plan, xray=body.xray, **_search_kw(body.filters))
    while True:
        with _search_lock:
            try:
                item = next(gen)
            except StopIteration:
                return
        yield item


async def _prepare(body: AskBody) -> dict:
    def _prep():
        for ev, data in _steps_gen(body):
            if ev == "result":
                return data
        raise RuntimeError("prepare_steps natija qaytarmadi")
    return await run_in_threadpool(_prep)


def _post(lang: str) -> dict:
    """Brauzer LLM javobini qanday qayta ishlaydi (serverdagi rag.AnswerStream bilan bir xil)."""
    return {"marker": MARKER, "translit": "lat2cyr" if lang == "uz_cyr" else None}


# ---------------------------------------------------------------- API
@app.post("/api/context")
async def context(body: AskBody):
    """Qidiruv + LLM uchun tayyor so'rov. Foydalanuvchi o'z kaliti bilan LLM'ni brauzerdan o'zi chaqiradi,
    shuning uchun kalit bu serverga umuman kelmaydi. no_answer=True bo'lsa LLM chaqirilmaydi."""
    t0 = time.time()
    if not STATE["ready"]:
        return JSONResponse({"code": "index", "message": "Qidiruv indeksi yuklanmagan. Server logini tekshiring."},
                            status_code=503)
    try:
        p = await _prepare(body)
    except Exception as e:  # noqa: BLE001
        log.exception("qidiruv xatosi")
        code, text = _human_error(e)
        return JSONResponse({"code": code, "message": text}, status_code=500)
    out = {"sources": p["sources"], "no_answer": p["no_answer"], "query_latin": prepare_query(body.question),
           "search_ms": int((time.time() - t0) * 1000), "no_answer_text": rag.NO_ANSWER_TEXT,
           "steps": p["steps"], "lang": p["lang"], "parts": p["parts"], "mode": body.mode,
           "post": _post(p["lang"]), "prompt": p["prompt"]}
    if p.get("xray"):
        # prompt matni javobning o'zida bor (prompt), X-ray'da faqat token soni qoladi
        out["xray"] = _xray_public(p["xray"], keep_prompt=False)
    return out


def _xray_public(x: dict, keep_prompt: bool = True) -> dict:
    x = {k: v for k, v in x.items() if not k.startswith("_")}
    if x.get("prompt") and not keep_prompt:
        x["prompt"] = {k: v for k, v in x["prompt"].items() if k not in ("system", "user")}
    return x


@app.post("/api/verify")
async def verify(body: VerifyBody):
    """Javobdagi har da'vo iqtibos qilingan moddada asosi bormi (raqamlar, leksik va ma'no o'xshashligi).
    LLM chaqirilmaydi; server va o'z kaliti yo'llari uchun bir xil."""
    if not STATE["ready"]:
        return JSONResponse({"code": "index", "message": "Qidiruv indeksi yuklanmagan."}, status_code=503)
    t0 = time.time()

    def _run():
        with _search_lock:
            return trust.check(body.text, body.chunk_ids, body.lang, body.mode)
    try:
        r = await run_in_threadpool(_run)
    except Exception:  # noqa: BLE001
        log.exception("verify xatosi")
        return JSONResponse({"code": "server", "message": "Tekshiruvda xato."}, status_code=500)
    return {**r, "ms": int((time.time() - t0) * 1000)}


OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"


@app.post("/api/proxy/openai/chat/completions", include_in_schema=False)
async def proxy_openai(request: Request):
    """OpenAI xato javoblarida (401, 429) CORS sarlavhasi yo'q: brauzer "noto'g'ri kalit"ni "tarmoq yo'q"dan
    ajrata olmaydi. Shuning uchun OpenAI so'rovi shu yerdan o'tadi (Gemini va Claude - to'g'ridan-to'g'ri).
    Kalit faqat shu so'rovning Authorization sarlavhasida keladi: hech qayerga yozilmaydi va logga tushmaydi."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or len(auth) > 400:
        return JSONResponse({"error": {"message": "Authorization sarlavhasi yoʻq", "code": "invalid_api_key"}}, status_code=401)
    body = await request.body()
    if len(body) > 256_000:
        return JSONResponse({"error": {"message": "Soʻrov juda katta"}}, status_code=413)
    client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=20))
    try:
        r = await client.send(client.build_request("POST", OPENAI_CHAT, content=body,
                                                   headers={"Authorization": auth, "Content-Type": "application/json"}),
                              stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("OpenAI proksi: %s", type(e).__name__)  # faqat xato turi: so'rov va sarlavhalar yozilmaydi
        return JSONResponse({"error": {"message": "OpenAI serveriga ulanib boʻlmadi", "code": "dalil_network"}}, status_code=502)

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in r.aiter_bytes():
                yield chunk
        finally:
            await r.aclose()
            await client.aclose()
    return StreamingResponse(relay(), status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"),
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/quota")
async def get_quota(request: Request):
    return _quota_info(_who(request))


@app.post("/api/ask")
async def ask(body: AskBody, request: Request):
    question = body.question.strip()
    keys = _who(request)
    q: quota.Quota = STATE["quota"]

    async def events() -> AsyncIterator[str]:
        t0 = time.time()
        if not STATE["ready"]:
            yield _sse("error", {"code": "index", "message": "Qidiruv indeksi yuklanmagan. Server logini tekshiring."})
            return
        p = None
        try:
            async for ev, data in iterate_in_threadpool(_steps_gen(body)):
                if ev == "step":
                    yield _sse("step", data)
                else:
                    p = data
        except Exception as e:  # noqa: BLE001
            log.exception("qidiruv xatosi")
            code, text = _human_error(e)
            yield _sse("error", {"code": code, "message": text})
            return
        yield _sse("sources", {"sources": p["sources"], "no_answer": p["no_answer"], "lang": p["lang"],
                               "parts": p["parts"], "mode": body.mode, "query_latin": prepare_query(question),
                               "search_ms": int((time.time() - t0) * 1000)})
        xr = p.get("xray")
        xt0 = xr["_t0"] if xr else None
        rel = (lambda: round((time.perf_counter() - xt0) * 1000, 1)) if xr else (lambda: None)
        if xr:
            info = _llm_info()
            yield _sse("xray", {**_xray_public(xr), "llm": {"via": "server", "provider": info["provider"],
                                                           "model": info["model"]}})
        if p["no_answer"]:
            yield _sse("delta", {"text": rag.NO_ANSWER_TEXT})
            yield _sse("done", {"no_answer": True, "model": None, "ms": int((time.time() - t0) * 1000)})
            return
        # bepul limit faqat server kaliti haqiqatan ishlatiladigan savolda sarflanadi
        counted = _llm_info()["configured"]
        if counted and not q.reserve(keys):
            st = _quota_info(keys)
            yield _sse("quota", st)
            yield _sse("error", {"code": "free_limit", "message": _limit_message(st), "reason": st["reason"]})
            return
        # LLM oqimi: <<<KEYINGI>>> qismi foydalanuvchiga ko'rsatilmaydi, kirill javob o'giriladi
        out = rag.AnswerStream(p["lang"])
        started = False
        llm_start, first_token = rel(), None
        try:
            async for piece in iterate_in_threadpool(llm.stream(p["prompt"]["system"], p["prompt"]["user"])):
                if not started:
                    first_token = rel()
                started = True
                if text := out.feed(piece):
                    yield _sse("delta", {"text": text})
        except asyncio.CancelledError:  # foydalanuvchi to'xtatdi / sahifani yopdi
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("LLM xatosi: %s", str(e)[:300])
            if counted and not started:  # javob umuman chiqmadi - savol hisobga olinmaydi
                q.refund(keys)
            code, text = _human_error(e)
            yield _sse("quota", _quota_info(keys))
            yield _sse("error", {"code": code, "message": text, "partial": started})
            return
        if text := out.flush():
            yield _sse("delta", {"text": text})
        if f := out.followups():
            yield _sse("followups", {"items": f})
        yield _sse("quota", _quota_info(keys))
        done = {"no_answer": out.not_found(), "model": llm.LAST_MODEL or _llm_info()["model"],
                "ms": int((time.time() - t0) * 1000)}
        if xr:  # LLM vaqtlari X-ray vaqt chizig'iga (qidiruv boshlanishidan hisoblanadi)
            done["xray_llm"] = {"start": llm_start, "first_token": first_token, "end": rel(), "model": done["model"]}
        yield _sse("done", done)

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
            "chunks": STATE["count"], "embedding_model": MODEL, "llm": _llm_info(),
            "free_daily_limit": quota.free_limit(), "global_daily_limit": quota.global_limit(),
            "telegram_auth": bool(os.environ.get("TELEGRAM_BOT_TOKEN"))}


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


# ---------------------------------------------------------------- baholash (/baholash sahifasi)
EVAL_RUN: dict = {"running": False, "done": 0, "total": 0, "current": "", "error": None, "started": None,
                  "finished": None}
_eval_lock = threading.Lock()


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@app.get("/api/eval")
async def get_eval():
    """eval/results.json + sweep.json + baseline (standart o'zgarishidan oldingi natija) + savollar (gold bilan)."""
    from .. import evaluate
    base = config.ROOT / "eval"
    return {"results": _read_json(evaluate.RESULTS), "sweep": _read_json(evaluate.SWEEP),
            "baseline": _read_json(base / "baseline_w06.json"), "answers": _read_json(base / "answers.json"),
            "run": EVAL_RUN, "protected": bool(os.environ.get("EVAL_TOKEN"))}


@app.get("/api/eval/status")
async def eval_status():
    return EVAL_RUN


@app.post("/api/eval/run")
async def eval_run(request: Request):
    """Baholashni fonda qayta hisoblash (faqat qidiruv, LLM'siz). Bir vaqtda bitta. .env da EVAL_TOKEN bo'lsa,
    X-Eval-Token sarlavhasi shu qiymatga teng bo'lishi kerak. Holat: GET /api/eval/status (polling)."""
    token = os.environ.get("EVAL_TOKEN", "")
    if token and request.headers.get("x-eval-token", "") != token:
        return JSONResponse({"code": "forbidden", "message": "Qayta hisoblash uchun ruxsat kaliti kerak (EVAL_TOKEN)."},
                            status_code=403)
    if not STATE["ready"]:
        return JSONResponse({"code": "index", "message": "Qidiruv indeksi yuklanmagan."}, status_code=503)
    if not _eval_lock.acquire(blocking=False):
        return JSONResponse({"code": "busy", "message": "Baholash allaqachon ishlayapti.", **EVAL_RUN}, status_code=409)
    EVAL_RUN.update(running=True, done=0, total=0, current="", error=None, started=time.time(), finished=None)

    def progress(i, n, q):
        EVAL_RUN.update(done=i, total=n, current=q[:120])

    def job():
        from .. import evaluate
        try:
            # har savol qidiruvi _search_lock ostida: chat savollari baholash orasida navbat bilan bajariladi
            evaluate.run(progress=progress, lock=_search_lock)
        except Exception as e:  # noqa: BLE001
            log.exception("baholash xatosi")
            EVAL_RUN["error"] = str(e)[:300]
        finally:
            EVAL_RUN.update(running=False, finished=time.time())
            _eval_lock.release()
    threading.Thread(target=job, daemon=True, name="eval").start()
    return EVAL_RUN


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
