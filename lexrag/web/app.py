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

Internetga ochiq server (ENV=production, Hugging Face Spaces - deploy/hf-space/):
    * port darhol ochiladi, indeks va model fonda yuklanadi: /api/health "status": "loading" -> "ready";
      tayyor bo'lguncha qidiruv endpointlari 503 {"code": "loading"} qaytaradi, frontend "Tayyorlanmoqda…" ko'rsatadi;
    * xavfsizlik sarlavhalari (CSP, nosniff, Referrer-Policy, Permissions-Policy, HSTS), rate limit (ratelimit.py),
      begona saytdan POST taqiqlanadi (Origin tekshiruvi), /api/docs va /api/openapi.json o'chiq,
      /api/eval/run faqat EVAL_TOKEN bilan, xatolarda stack trace ko'rsatilmaydi.
"""
from __future__ import annotations

import asyncio
import hmac
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
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from .. import config, llm, rag, trust
from . import bootstrap, quota, ratelimit
from ..lang import MARKER
from ..retrieval import MODEL, _bm25, prepare_query, vocab
from ..indexer import embed_query, get_collection

log = logging.getLogger("lexrag.web")
llm.load_env()
PRODUCTION = os.environ.get("ENV", "").strip().lower() == "production"
# DALIL_DIST: boshqa papkadagi frontend yig'masi (masalan, sinov serveri uchun)
DIST = Path(os.environ.get("DALIL_DIST") or config.ROOT / "web" / "dist")
DOC_TYPES = ["Qonun", "Kodeks", "Konstitutsiya"]
# phase: start -> download (indeks yuklanmoqda) -> model (bge-m3) -> index (BM25, ChromaDB) -> ready | error
STATE: dict = {"ready": False, "error": None, "count": None, "phase": "start", "phase_detail": "", "started": time.time(),
               "ready_s": None}
# ONNX va ChromaDB bir vaqtda bitta qidiruvni bajaradi (CPU baribir band)
_search_lock = threading.Lock()


def _phase(name: str, detail: str = ""):
    STATE["phase"], STATE["phase_detail"] = name, detail


def _warmup():
    t0 = time.time()
    try:
        bootstrap.ensure_data(_phase)      # konteynerda: HF dataset'dan indeks (bor bo'lsa - hech narsa)
        _phase("model", "model yuklanmoqda")  # qisqa: telefondagi chipga sig'sin
        embed_query(MODEL, "salom")      # bge-m3 ONNX modeli xotiraga
        _phase("index", "indeks ochilmoqda")
        _bm25()                          # BM25 indeksi
        vocab()                          # so'z tiklash lug'ati (4-bosqich indeksida bor)
        STATE["count"] = get_collection(MODEL, create=False).count()
        STATE["ready"] = True
        STATE["ready_s"] = round(time.time() - STATE["started"], 1)
        _phase("ready")
        log.info("Model va indeks yuklandi: %.1fs, %s chunk", time.time() - t0, STATE["count"])
    except Exception as e:  # noqa: BLE001 - server ishlayveradi, /api/health xatoni ko'rsatadi
        STATE["error"] = str(e)
        _phase("error", "Qidiruv indeksini yuklab boʻlmadi")
        log.exception("Indeksni yuklab bo'lmadi")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    STATE["quota"] = quota.Quota()
    STATE["rate"] = ratelimit.RateLimiter()
    # port darhol ochiladi (HF Spaces "uyg'onish"i 1-2 daqiqa): indeks va model fonda yuklanadi
    threading.Thread(target=_warmup, daemon=True, name="warmup").start()
    yield


app = FastAPI(title="Dalil", lifespan=lifespan,
              docs_url=None if PRODUCTION else "/api/docs", redoc_url=None,
              openapi_url=None if PRODUCTION else "/api/openapi.json")


# ---------------------------------------------------------------- xavfsizlik (sarlavhalar, rate limit, Origin)
def _csp() -> str:
    """Content-Security-Policy. Telegram Web (web.telegram.org) Mini App'ni iframe'da ochadi, Hugging Face esa
    Space sahifasini huggingface.co ichida iframe'da ko'rsatadi: shuning uchun X-Frame-Options qo'yilmaydi,
    ruxsat frame-ancestors bilan beriladi. FRAME_ANCESTORS_EXTRA - qo'shimcha manzillar (bo'sh joy bilan)."""
    frames = "'self' https://web.telegram.org https://*.telegram.org https://huggingface.co https://*.hf.space"
    if extra := os.environ.get("FRAME_ANCESTORS_EXTRA", "").strip():
        frames += " " + extra
    return "; ".join([
        "default-src 'self'",
        "script-src 'self' https://telegram.org",
        # style="animation-delay:..." (render.ts) va React inline uslublari
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob:",
        # o'z kaliti: Gemini va Claude brauzerdan to'g'ridan-to'g'ri, OpenAI - /api/proxy/openai orqali
        "connect-src 'self' https://generativelanguage.googleapis.com https://api.anthropic.com",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        f"frame-ancestors {frames}",
    ])


CSP = _csp()
SEC_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    # mikrofon keyinroq (ovozli savol) kerak bo'ladi - faqat o'z sahifamizga
    (b"permissions-policy", b"microphone=(self), camera=(), geolocation=(), payment=(), usb=(), interest-cohort=()"),
] + ([(b"strict-transport-security", b"max-age=31536000")] if PRODUCTION else [])


def _allowed_origin(origin: str, headers) -> bool:
    """POST so'rovi faqat o'z sahifamizdan (yoki ALLOWED_ORIGINS dan): begona sayt foydalanuvchi brauzeri orqali
    bepul limitni sarflay olmasin. Origin sarlavhasi yo'q (curl, server) - rate limit baribir ishlaydi."""
    if not origin:
        return True
    net = urlsplit(origin).netloc.lower()
    hosts = {(headers.get("host") or "").lower(), (headers.get("x-forwarded-host") or "").lower()} - {""}
    extra = {o.strip().rstrip("/").lower() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()}
    return net in hosts or origin.rstrip("/").lower() in extra


class SecurityMiddleware:
    """Toza ASGI middleware (SSE oqimini buferlamaydi): sarlavhalar, Origin tekshiruvi, rate limit."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope.get("path", ""), scope.get("method", "GET")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        host = (scope.get("client") or (None,))[0]

        async def deny(status: int, body: dict, extra: list | None = None):
            await JSONResponse(body, status_code=status, headers=dict(extra or []))(scope, receive, wrapped)

        async def wrapped(msg):
            if msg["type"] == "http.response.start":
                h = list(msg.get("headers") or [])
                h += SEC_HEADERS
                if path.startswith("/assets/") and msg.get("status") == 200:  # Vite: fayl nomida xesh bor
                    h.append((b"cache-control", b"public, max-age=31536000, immutable"))
                msg = {**msg, "headers": h}
            await send(msg)

        if path.startswith("/api/") and method not in ("GET", "HEAD", "OPTIONS") \
                and not _allowed_origin(headers.get("origin", ""), headers):
            return await deny(403, {"code": "origin", "message": "Bu manzildan soʻrov qabul qilinmaydi."})
        if ratelimit.limited(path) and method != "OPTIONS" and "rate" in STATE:
            ok, retry, why = STATE["rate"].check(ratelimit.keys_for(host, headers))
            if not ok:
                msg = ("Juda koʻp soʻrov: bir daqiqa kutib, qayta urinib koʻring." if why == "min" else
                       "Bugungi soʻrovlar limiti tugadi. Ertaga qayta urinib koʻring.")
                return await deny(429, {"code": "rate_limit", "message": msg, "retry_after": retry},
                                  [("Retry-After", str(retry))])
        return await self.app(scope, receive, wrapped)


app.add_middleware(SecurityMiddleware)


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception):
    """Kutilmagan xato: foydalanuvchiga stack trace emas, umumiy xabar (tafsilot faqat server logida)."""
    log.error("Kutilmagan xato: %s", type(exc).__name__, exc_info=exc)
    return JSONResponse({"code": "server", "message": "Serverda kutilmagan xato yuz berdi."}, status_code=500)


def _loading_body() -> dict:
    if STATE["phase"] == "error":
        return {"code": "index", "message": "Qidiruv indeksi yuklanmadi. Server egasi logni tekshirsin."}
    return {"code": "loading", "message": "Server tayyorlanmoqda (qidiruv indeksi va til modeli yuklanmoqda). "
                                          "Bir daqiqadan keyin qayta urinib koʻring.", "phase": STATE["phase"]}


def _not_ready() -> JSONResponse:
    return JSONResponse(_loading_body(), status_code=503, headers={"Retry-After": "10"})


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
        return _not_ready()
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
        return _not_ready()
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


OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"  # yagona manzil: boshqa URL'ga o'tkazilmaydi
# frontenddagi ro'yxat (web/src/ai.ts) + yaqin modellar; OPENAI_MODELS (vergul bilan) bilan almashtiriladi
OPENAI_MODELS_DEFAULT = "gpt-4.1-mini,gpt-4.1-nano,gpt-4.1,gpt-5-mini,gpt-5-nano,gpt-4o-mini"
OPENAI_MAX_BODY = 200_000       # bayt: prompt (8 ta modda + sodda rejimda yuridik javob) ~60 KB
OPENAI_MAX_TOKENS = 8192
OPENAI_TOTAL_S = 180            # bitta javob oqimining eng uzoq davomiyligi
_BEARER = re.compile(r"^Bearer [A-Za-z0-9_\-.]{20,300}$")


def _openai_models() -> set[str]:
    return {m.strip() for m in (os.environ.get("OPENAI_MODELS") or OPENAI_MODELS_DEFAULT).split(",") if m.strip()}


def _openai_body(raw: bytes) -> dict | str:
    """Brauzer so'rovini tekshirib, faqat ruxsat etilgan maydonlar bilan qayta yig'adi. Xato bo'lsa - matn."""
    try:
        d = json.loads(raw)
    except ValueError:
        return "Soʻrov JSON emas"
    if not isinstance(d, dict):
        return "Soʻrov JSON obyekt emas"
    model = d.get("model")
    if model not in _openai_models():
        return "Bu model proksi orqali ruxsat etilmagan"
    msgs = d.get("messages")
    if not isinstance(msgs, list) or not 1 <= len(msgs) <= 4 or not all(
            isinstance(m, dict) and m.get("role") in ("system", "user") and isinstance(m.get("content"), str)
            for m in msgs):
        return "messages notoʻgʻri"
    out: dict = {"model": model, "messages": [{"role": m["role"], "content": m["content"]} for m in msgs],
                 "stream": bool(d.get("stream", False))}
    for k in ("max_completion_tokens", "max_tokens"):
        if k in d:
            if not isinstance(d[k], int) or isinstance(d[k], bool) or d[k] < 1:
                return f"{k} notoʻgʻri"
            out[k] = min(d[k], OPENAI_MAX_TOKENS)
    if "max_completion_tokens" not in out and "max_tokens" not in out:
        out["max_completion_tokens"] = OPENAI_MAX_TOKENS
    if "temperature" in d:
        t = d["temperature"]
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not 0 <= t <= 2:
            return "temperature notoʻgʻri"
        out["temperature"] = t
    return out


@app.post("/api/proxy/openai/chat/completions", include_in_schema=False)
async def proxy_openai(request: Request):
    """OpenAI xato javoblarida (401, 429) CORS sarlavhasi yo'q: brauzer "noto'g'ri kalit"ni "tarmoq yo'q"dan
    ajrata olmaydi. Shuning uchun OpenAI so'rovi shu yerdan o'tadi (Gemini va Claude - to'g'ridan-to'g'ri).
    Kalit faqat shu so'rovning Authorization sarlavhasida keladi: hech qayerga yozilmaydi va logga tushmaydi.

    Ochiq "relay" bo'lib qolmasligi uchun: faqat api.openai.com/v1/chat/completions, model ro'yxati (OPENAI_MODELS),
    body qayta yig'iladi (faqat model, messages, stream, max_*tokens, temperature), hajm va vaqt cheklovi, rate limit."""
    auth = request.headers.get("authorization", "")
    if not _BEARER.match(auth):
        return JSONResponse({"error": {"message": "Authorization sarlavhasi yoʻq yoki notoʻgʻri", "code": "invalid_api_key"}},
                            status_code=401)
    if int(request.headers.get("content-length") or 0) > OPENAI_MAX_BODY:
        return JSONResponse({"error": {"message": "Soʻrov juda katta"}}, status_code=413)
    raw = b""
    async for part in request.stream():
        raw += part
        if len(raw) > OPENAI_MAX_BODY:
            return JSONResponse({"error": {"message": "Soʻrov juda katta"}}, status_code=413)
    body = _openai_body(raw)
    if isinstance(body, str):
        return JSONResponse({"error": {"message": body, "code": "dalil_bad_request"}}, status_code=400)
    client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=20), follow_redirects=False)
    try:
        r = await client.send(client.build_request("POST", OPENAI_CHAT, json=body,
                                                   headers={"Authorization": auth, "Content-Type": "application/json"}),
                              stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("OpenAI proksi: %s", type(e).__name__)  # faqat xato turi: so'rov va sarlavhalar yozilmaydi
        return JSONResponse({"error": {"message": "OpenAI serveriga ulanib boʻlmadi", "code": "dalil_network"}}, status_code=502)

    async def relay() -> AsyncIterator[bytes]:
        deadline = time.monotonic() + OPENAI_TOTAL_S
        try:
            async for chunk in r.aiter_bytes():
                yield chunk
                if time.monotonic() > deadline:
                    log.warning("OpenAI proksi: %ss dan oshdi, oqim uzildi", OPENAI_TOTAL_S)
                    break
        except httpx.HTTPError as e:
            log.warning("OpenAI proksi oqimi: %s", type(e).__name__)
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
            yield _sse("error", _loading_body())
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
        b = _loading_body()
        return JSONResponse({**b, "error": b["message"]}, status_code=503, headers={"Retry-After": "10"})
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
    """status: loading (indeks/model yuklanmoqda) | ready | error. Production'da xato tafsiloti ko'rsatilmaydi."""
    status = "ready" if STATE["ready"] else "error" if STATE["phase"] == "error" else "loading"
    err = STATE["error"]
    return {"ok": STATE["ready"], "status": status, "phase": STATE["phase"], "phase_detail": STATE["phase_detail"],
            "uptime_s": round(time.time() - STATE["started"], 1), "ready_s": STATE["ready_s"],
            "index_ready": STATE["ready"], "index_error": ("indeks yuklanmadi" if PRODUCTION else err) if err else None,
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
    from ..eval_report import web_extras
    base = config.ROOT / "eval"
    return {"results": _read_json(evaluate.RESULTS), "sweep": _read_json(evaluate.SWEEP),
            "baseline": _read_json(base / "baseline_w06.json"), "answers": _read_json(base / "answers.json"),
            **web_extras(),   # baseline_v2 (4-bosqichdan oldin, shu to'plamda), trust_cal (ruscha ishonch kalibrlash)
            "run": EVAL_RUN, "protected": bool(os.environ.get("EVAL_TOKEN")),
            "run_disabled": PRODUCTION and not os.environ.get("EVAL_TOKEN")}


@app.get("/api/eval/status")
async def eval_status():
    return EVAL_RUN


@app.post("/api/eval/run")
async def eval_run(request: Request):
    """Baholashni fonda qayta hisoblash (faqat qidiruv, LLM'siz). Bir vaqtda bitta. .env da EVAL_TOKEN bo'lsa,
    X-Eval-Token sarlavhasi shu qiymatga teng bo'lishi kerak. Holat: GET /api/eval/status (polling)."""
    token = os.environ.get("EVAL_TOKEN", "")
    if PRODUCTION and not token:  # internetda tokensiz qayta hisoblash o'chiq (170 savol CPU'ni ~1 daqiqa band qiladi)
        return JSONResponse({"code": "disabled", "message": "Bu serverda qayta hisoblash oʻchirilgan."}, status_code=403)
    if token and not hmac.compare_digest(request.headers.get("x-eval-token", "").encode(), token.encode()):
        return JSONResponse({"code": "forbidden", "message": "Qayta hisoblash uchun ruxsat kaliti kerak (EVAL_TOKEN)."},
                            status_code=403)
    if not STATE["ready"]:
        return _not_ready()
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
            EVAL_RUN["error"] = "Baholashda xato (tafsilot server logida)." if PRODUCTION else str(e)[:300]
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
