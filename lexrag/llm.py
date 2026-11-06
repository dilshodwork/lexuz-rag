"""LLM provayderlari: Gemini, OpenAI, Claude (Anthropic). SDK'siz, to'g'ridan HTTP (httpx).

Sozlash loyiha papkasidagi .env faylida (git'ga tushmaydi):
    LLM_PROVIDER=gemini            # gemini | openai | anthropic
    GEMINI_API_KEY=...
    OPENAI_API_KEY=...
    ANTHROPIC_API_KEY=...
    LLM_MODEL=                     # ixtiyoriy; bo'sh bo'lsa pastdagi standart model
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Iterator

import httpx

from . import config

log = logging.getLogger(__name__)

DEFAULT_MODELS = {
    # 2.5-flash yangi kalitlarga berilmaydi (404); 3.8-flash 31.10.2026 da tez-tez 503 yoki osilib qoladi;
    # 3.5-flash bepul tarifda kuniga ~20 so'rov - server kaliti (bepul sinov rejimi) uchun flash-lite
    "gemini": "gemini-3.1-flash-lite",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-4-5",
}
KEY_VARS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def load_env():
    p = config.ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")  # qator oxiridagi izohni olib tashlash
        if v:
            os.environ.setdefault(k.strip(), v)


def settings() -> tuple[str, str, str]:
    load_env()
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not provider:  # birinchi kaliti bor provayder
        provider = next((p for p, v in KEY_VARS.items() if os.environ.get(v)), "")
    if provider not in KEY_VARS:
        raise RuntimeError("LLM sozlanmagan: .env ga LLM_PROVIDER va mos API kalitni yozing (README).")
    key = os.environ.get(KEY_VARS[provider], "")
    if not key:
        raise RuntimeError(f"{KEY_VARS[provider]} .env da yo'q.")
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS[provider]
    return provider, model, key


def _client():
    # read=60: bo'laklar orasidagi eng uzoq kutish; osilib qolgan model zaxirasiga tezroq o'tiladi
    return httpx.Client(timeout=httpx.Timeout(60, connect=20))


# Gemini 3.x da "thinking" tokenlari ham maxOutputTokens ichiga kiradi: 2048 da javob o'rtada uzilardi
def stream(system: str, user: str, temperature: float = 0.1, max_tokens: int = 8192,
           seed: int | None = None) -> Iterator[str]:
    """Javobni bo'laklab qaytaradi (UI'da so'zma-so'z chiqishi uchun).

    Gemini 503/429 (yuklama), 404 (model yo'q) yoki timeout bo'lsa, birinchi bo'lak chiqmaguncha
    qayta urinadi va GEMINI_FALLBACKS dagi zaxira modellarga o'tadi.
    """
    provider, model, key = settings()
    LAST.model, LAST.usage = model, {}
    if provider != "gemini":
        yield from _stream_once(provider, model, key, system, user, temperature, max_tokens, seed)
        return
    import time
    chain = [model] + [m for m in GEMINI_FALLBACKS if m != model]
    last: Exception | None = None
    first: Exception | None = None
    for m in chain:
        for attempt in range(2):
            started = False
            t0 = time.time()
            try:
                for piece in _stream_once(provider, m, key, system, user, temperature, max_tokens, seed):
                    if not started:
                        global LAST_MODEL
                        LAST_MODEL = m
                        LAST.model = m
                    started = True
                    yield piece
                return
            except (LLMBusy, LLMNoModel, httpx.TimeoutException) as e:
                if started:
                    raise
                log.warning("LLM %s: %s (%.1fs) - %s", m, type(e).__name__, time.time() - t0,
                            "qayta urinish" if isinstance(e, LLMBusy) and attempt == 0 else "keyingi model")
                last = e
                first = first or e
                if not isinstance(e, LLMBusy) or isinstance(e, LLMQuota):
                    break  # 404 / osilib qolish / kunlik limit: shu modelni qayta urinmasdan keyingisiga
                time.sleep(1.5 * (attempt + 1))
    # asosiy modelning kunlik limiti tugagan bo'lsa, foydalanuvchiga aynan shu sabab aytiladi
    raise (first if isinstance(first, LLMQuota) else last) or RuntimeError("LLM javob bermadi")


# 31.10.2026 sinovi: 3.5-flash barqaror (~10-20 s), 3.8-flash tez-tez 503, flash-latest osilib qoladi.
# Har modelning kunlik kvotasi alohida, shuning uchun 3.5-flash ham zaxirada.
GEMINI_FALLBACKS = ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"]
LAST_MODEL: str | None = None  # oxirgi javobni yozgan model (UI/log uchun)
# shu oqimdagi (thread) oxirgi chaqiruv: model va tokenlar - /v1 API har savol uchun qaytaradi
LAST = threading.local()


class LLMBusy(RuntimeError):
    """Provayder vaqtincha band (503/429)."""


class LLMQuota(LLMBusy):
    """Kunlik kvota tugagan (429, ...PerDay...): qayta urinish befoyda, boshqa modelning kvotasi alohida."""


class LLMNoModel(RuntimeError):
    """Bunday model yo'q yoki bu kalitga berilmaydi (404)."""


def _stream_once(provider, model, key, system, user, temperature, max_tokens, seed=None) -> Iterator[str]:
    with _client() as c:
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
            body = {"system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
            if seed is not None:
                body["generationConfig"]["seed"] = seed
            with c.stream("POST", url, json=body, headers={"x-goog-api-key": key}) as r:
                _raise(r)
                finish, usage = None, {}
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        d = json.loads(line[5:])
                        usage = d.get("usageMetadata") or usage
                        for cand in d.get("candidates", []):
                            finish = cand.get("finishReason") or finish
                            for part in cand.get("content", {}).get("parts", []):
                                if part.get("text") and not part.get("thought"):
                                    yield part["text"]
                LAST.usage = {"input_tokens": usage.get("promptTokenCount"),
                              "output_tokens": usage.get("candidatesTokenCount")}
                if finish and finish != "STOP":
                    log.warning("Gemini %s javobi to'liq emas: finishReason=%s, tokenlar=%s", model, finish, usage)
        elif provider == "openai":
            body = {"model": model, "temperature": temperature, "max_tokens": max_tokens, "stream": True,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if seed is not None:
                body["seed"] = seed
            with c.stream("POST", "https://api.openai.com/v1/chat/completions", json=body,
                          headers={"Authorization": f"Bearer {key}"}) as r:
                _raise(r)
                for line in r.iter_lines():
                    if line.startswith("data:") and line.strip() != "data: [DONE]":
                        d = json.loads(line[5:])
                        delta = d["choices"][0]["delta"].get("content") if d.get("choices") else None
                        if delta:
                            yield delta
        else:  # anthropic
            body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "stream": True,
                    "system": system, "messages": [{"role": "user", "content": user}]}
            with c.stream("POST", "https://api.anthropic.com/v1/messages", json=body,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01"}) as r:
                _raise(r)
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        d = json.loads(line[5:])
                        if d.get("type") == "content_block_delta":
                            t = d.get("delta", {}).get("text")
                            if t:
                                yield t


def complete(system: str, user: str, **kw) -> str:
    return "".join(stream(system, user, **kw))


def _raise(r: httpx.Response):
    if r.status_code >= 400:
        r.read()
        msg = r.text[:400]
        if r.status_code == 429 and "PerDay" in r.text:
            raise LLMQuota(f"LLM API xatosi 429 (kunlik limit): {msg}")
        if r.status_code in (429, 503):
            raise LLMBusy(f"LLM API xatosi {r.status_code}: {msg}")
        if r.status_code == 404:
            raise LLMNoModel(f"LLM API xatosi {r.status_code}: {msg}")
        raise RuntimeError(f"LLM API xatosi {r.status_code}: {msg}")
