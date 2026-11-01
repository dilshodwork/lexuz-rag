"""Internetga chiqarish xavfsizligi: LLM'siz, model va indeks yuklanmaydi (lifespan ishga tushmaydi).

    .venv/bin/python scripts/test_deploy.py

Tekshiriladi: xavfsizlik sarlavhalari (CSP, frame-ancestors, X-Frame-Options yo'qligi), production'da /api/docs va
/api/openapi.json o'chiqligi, /api/eval/run EVAL_TOKEN'siz o'chiq, begona Origin'dan POST taqiqlangani, rate limit
(daqiqa / kun, IP x factor), TRUST_PROXY va X-Forwarded-For soxtalashtirish, OpenAI proksisi (model ro'yxati, maydonlar,
hajm, Authorization formati), indeks yuklanguncha "loading", stack trace ko'rinmasligi, render.ts XSS (node).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.update(ENV="production", TRUST_PROXY="1", RATE_LIMIT_PER_MIN="5", RATE_LIMIT_PER_DAY="8",
                  RATE_IP_FACTOR="2", EVAL_TOKEN="")
os.environ.pop("EVAL_TOKEN")

from fastapi.testclient import TestClient  # noqa: E402

from lexrag.web import app as web  # noqa: E402
from lexrag.web import quota, ratelimit  # noqa: E402

FAILS = 0


def ok(cond, name, detail=""):
    global FAILS
    print(("  ok  " if cond else "  XATO") + f" {name}" + (f" - {detail}" if detail and not cond else ""))
    FAILS += 0 if cond else 1


def client() -> TestClient:
    web.STATE["rate"] = ratelimit.RateLimiter()
    web.STATE.setdefault("quota", quota.Quota(Path(tempfile.mkdtemp(prefix="dalil-test-")) / "quota.sqlite"))
    return TestClient(web.app, base_url="https://dalil.hf.space")  # lifespan yo'q: model yuklanmaydi


def main():
    print("Sarlavhalar va production rejimi")
    c = client()
    r = c.get("/api/health")
    csp = r.headers.get("content-security-policy", "")
    ok(r.status_code == 200 and r.json()["status"] == "loading", "health: indeks yuklanguncha status=loading")
    ok("frame-ancestors 'self' https://web.telegram.org https://*.telegram.org https://huggingface.co" in csp,
       "CSP frame-ancestors: Telegram Web va huggingface.co", csp)
    ok("script-src 'self' https://telegram.org;" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0],
       "CSP script-src: self + telegram.org, inline skript yo'q")
    ok("connect-src 'self' https://generativelanguage.googleapis.com https://api.anthropic.com" in csp, "CSP connect-src")
    ok("x-frame-options" not in r.headers, "X-Frame-Options yo'q (Telegram Web iframe'i uchun)")
    ok(r.headers.get("x-content-type-options") == "nosniff", "X-Content-Type-Options: nosniff")
    ok(r.headers.get("referrer-policy") == "strict-origin-when-cross-origin", "Referrer-Policy")
    ok("microphone=(self)" in r.headers.get("permissions-policy", ""), "Permissions-Policy: microphone=(self)")
    ok("max-age" in r.headers.get("strict-transport-security", ""), "HSTS (production)")
    ok("access-control-allow-origin" not in r.headers, "CORS sarlavhasi yo'q (faqat o'z origin)")
    for p in ("/api/docs", "/api/openapi.json", "/docs", "/redoc"):
        rr = c.get(p)
        ok("swagger" not in rr.text.lower() and '"openapi":' not in rr.text[:200] and
           (rr.status_code == 404 or "<div id=\"root\">" in rr.text or rr.status_code == 503),
           f"{p} production'da o'chiq", f"{rr.status_code} {rr.text[:120]}")
    rr = c.post("/api/eval/run")
    ok(rr.status_code == 403 and rr.json()["code"] == "disabled", "/api/eval/run: EVAL_TOKEN'siz o'chiq")
    ok(c.get("/api/eval").json().get("run_disabled") is True, "/api/eval: run_disabled=true")

    print("Indeks yuklanguncha")
    rr = c.get("/api/search", params={"q": "taʼtil"}, headers={"x-device-id": "loadtest01"})
    ok(rr.status_code == 503 and rr.json()["code"] == "loading" and rr.headers.get("retry-after"), "/api/search -> 503 loading")
    rr = c.post("/api/context", json={"question": "salom"}, headers={"x-device-id": "loadtest02"})
    ok(rr.status_code == 503 and rr.json()["code"] == "loading", "/api/context -> 503 loading")
    rr = c.post("/api/ask", json={"question": "salom"}, headers={"x-device-id": "loadtest03"})
    ok("event: error" in rr.text and '"loading"' in rr.text, "/api/ask -> SSE error loading")

    print("Origin (begona saytdan POST)")
    c = client()
    rr = c.post("/api/context", json={"question": "x"}, headers={"origin": "https://evil.example"})
    ok(rr.status_code == 403 and rr.json()["code"] == "origin", "begona Origin -> 403")
    rr = c.post("/api/context", json={"question": "x"}, headers={"origin": "https://dalil.hf.space"})
    ok(rr.status_code == 503, "o'z Origin -> o'tadi")
    rr = c.post("/api/context", json={"question": "x"}, headers={"origin": "null"})
    ok(rr.status_code == 403, "Origin: null -> 403")

    print("Rate limit (daqiqa=5, kun=8, IP x2)")
    c = client()
    xff = {"x-forwarded-for": "203.0.113.7"}
    codes = [c.get("/api/search", params={"q": "a"}, headers={**xff, "x-device-id": "deviceAAA1"}).status_code for _ in range(6)]
    ok(codes[:5] == [503] * 5 and codes[5] == 429, "qurilma: 6-so'rov daqiqada 429", str(codes))
    r429 = c.get("/api/search", params={"q": "a"}, headers={**xff, "x-device-id": "deviceAAA1"})
    ok(r429.json()["code"] == "rate_limit" and int(r429.headers["retry-after"]) > 0, "429: code=rate_limit, Retry-After")
    codes = [c.get("/api/search", params={"q": "a"}, headers={**xff, "x-device-id": f"devroll{i:04d}"}).status_code
             for i in range(6)]
    ok(429 in codes, "IP: qurilma ID'ni almashtirib chetlab o'tib bo'lmaydi (IP limiti 10)", str(codes))
    ok(c.get("/api/health", headers=xff).status_code == 200, "health va statik fayllar cheklanmaydi")
    rl = ratelimit.RateLimiter()
    keys = [("dev:x", 1)]
    res = [rl.check(keys, now=1000 + i * 30)[0] for i in range(9)]  # daqiqasiga 2 ta - daqiqa limiti ishlamaydi
    ok(res[:8] == [True] * 8 and res[8] is False and rl.check(keys, now=5000)[2] == "day", "kunlik limit (8)", str(res))
    rl2 = ratelimit.RateLimiter()
    ok(all(rl2.check([("dev:y", 1)], now=0)[0] for _ in range(5)) and not rl2.check([("dev:y", 1)], now=1)[0]
       and rl2.check([("dev:y", 1)], now=61)[0], "daqiqa oynasi 60 s dan keyin bo'shaydi")

    print("IP aniqlash (TRUST_PROXY=1)")
    # 198.51.100.0/24 kabi hujjat diapazonlari Python'da "private" - haqiqiy ochiq manzillar ishlatiladi
    ok(quota.client_ip("10.0.0.5", {"x-forwarded-for": "1.2.3.4, 84.54.70.9, 10.1.2.3"}) == "84.54.70.9",
       "XFF: o'ngdan birinchi public IP (chapdagi soxta 1.2.3.4 emas)")
    ok(quota.client_ip("10.0.0.5", {"x-forwarded-for": "84.54.70.9"}) == "84.54.70.9", "XFF: bitta IP")
    ok(quota.client_ip("10.0.0.5", {}) == "10.0.0.5", "XFF yo'q -> ulanish manzili")
    os.environ["TRUST_PROXY"] = "0"
    ok(quota.client_ip("84.54.70.1", {"x-forwarded-for": "1.2.3.4"}) == "84.54.70.1",
       "TRUST_PROXY=0: tashqi so'rovdagi XFF'ga ishonilmaydi")
    os.environ["TRUST_PROXY"] = "1"

    print("OpenAI proksisi")
    os.environ["RATE_LIMIT_PER_MIN"] = "1000"  # bu bo'limda rate limit emas, proksi tekshiruvlari sinaladi
    os.environ["RATE_LIMIT_PER_DAY"] = "1000"
    c = client()
    good = {"model": "gpt-4.1-mini", "stream": True, "max_completion_tokens": 100, "temperature": 0.1,
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]}
    auth = {"authorization": "Bearer sk-test-" + "a" * 30}
    P = "/api/proxy/openai/chat/completions"
    ok(c.post(P, json=good).status_code == 401, "Authorization yo'q -> 401")
    ok(c.post(P, json=good, headers={"authorization": "Bearer short key"}).status_code == 401,
       "Authorization formati noto'g'ri -> 401")
    ok(c.post(P, json={**good, "model": "o1-pro"}, headers=auth).status_code == 400, "ro'yxatda yo'q model -> 400")
    ok(c.post(P, json={**good, "messages": [{"role": "tool", "content": "x"}]}, headers=auth).status_code == 400,
       "messages: faqat system/user")
    ok(c.post(P, json={**good, "temperature": 5}, headers=auth).status_code == 400, "temperature diapazoni")
    ok(c.post(P, content=b"x" * 210_000, headers={**auth, "content-type": "application/json"}).status_code == 413,
       "200 KB dan katta -> 413")
    b = web._openai_body(json.dumps({**good, "max_completion_tokens": 10**6, "n": 50, "tools": [{"x": 1}],
                                     "user": "x"}).encode())
    ok(isinstance(b, dict) and b["max_completion_tokens"] == web.OPENAI_MAX_TOKENS and "n" not in b and "tools" not in b,
       "body qayta yig'iladi: n/tools tashlanadi, max tokens cheklanadi", str(b)[:200])
    ok(web.OPENAI_CHAT == "https://api.openai.com/v1/chat/completions", "faqat api.openai.com chat/completions")

    print("Xatolar")
    c = TestClient(web.app, raise_server_exceptions=False)
    web.STATE["rate"] = ratelimit.RateLimiter()

    @web.app.get("/api/__boom_test")
    async def _boom():
        raise ValueError("maxfiy /home/user/app/lexrag/x.py")
    # catch-all /api/{rest} dan oldin turishi uchun yo'nalishni boshiga ko'chiramiz
    web.app.router.routes.insert(0, web.app.router.routes.pop())
    rr = c.get("/api/__boom_test")
    ok(rr.status_code == 500 and "Traceback" not in rr.text and "maxfiy" not in rr.text and rr.json()["code"] == "server",
       "kutilmagan xato: stack trace va tafsilot ko'rinmaydi", rr.text[:200])

    print("render.ts XSS (node)")
    p = subprocess.run(["node", str(ROOT / "scripts" / "test_render.mjs")], capture_output=True, text=True)
    print(p.stdout.rstrip())
    ok(p.returncode == 0, "test_render.mjs", p.stderr[-600:])

    print(f"\n{'HAMMASI OK' if not FAILS else f'{FAILS} ta XATO'}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
