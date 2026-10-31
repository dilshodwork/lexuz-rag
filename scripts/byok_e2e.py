""""AI ulash" va bepul limit sinovi (Playwright). Sinov serverini o'zi ishga tushiradi va oxirida to'xtatadi.

    cd web && npx vite build --outDir /tmp/dalil-byok-dist --emptyOutDir && cd ..
    .venv/bin/python scripts/byok_e2e.py [--only api,free,keys,byok,mock,tg,mobile]

Haqiqiy LLM so'rovi faqat "free" bosqichida: server kaliti bilan 2 ta savol (limit 2).
"keys" va "byok" provayderlarga SOXTA kalit bilan haqiqiy so'rov yuboradi (rad etiladi, kvota sarflanmaydi).
"mock" - faqat oqim parserini tekshiradi: provayder javobi brauzer ichida almashtiriladi (haqiqiy javob emas).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8010
BASE = f"http://127.0.0.1:{PORT}"
OUT = ROOT / "design" / "shots" / "app"
CONVS = Path("/tmp/dalil-e2e-convs.json")
TG_TOKEN = "123456:DALIL-E2E-FAKE"
DESK = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}
MOB = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
       "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"}
DEV_DESK, DEV_MOB = "e2e-desk-0001", "e2e-mob-00001"
# soxta kalitlar (atayin qisqa va "FAKE"): provayder rad etadi
FAKE = {"gemini": "AIza-FAKE-dalil-test", "openai": "sk-FAKE-dalil-test", "anthropic": "sk-ant-FAKE-dalil"}
Q1, Q2, Q3 = "Yillik mehnat taʼtili necha kun?", "Prezident qancha muddatga saylanadi?", "Ijara shartnomasi qanday shaklda tuziladi?"

results: list[tuple[bool, str]] = []
llm_calls = 0


def ok(cond, name, info=""):
    results.append((bool(cond), name))
    print(f"{'OK  ' if cond else 'XATO'} {name}" + (f" — {info}" if info else ""), flush=True)
    return cond


def shot(page: Page, name: str):
    p = OUT / f"byok-{name}.png"
    page.screenshot(path=str(p))
    print("     ", p.relative_to(ROOT))


def signed_init_data(uid: int) -> str:
    f = {"auth_date": str(int(time.time())), "query_id": "AAE2e", "user": json.dumps({"id": uid, "first_name": "E2E"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    secret = hmac.new(b"WebAppData", TG_TOKEN.encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(f)


def sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.split("\n\n"):
        ev, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            out.append((ev, json.loads(data)))
    return out


def new_page(b, opts, device: str, theme="light", ai: dict | None = None, convs=None, init_script=""):
    ctx = b.new_context(**opts)
    seed = {"dalil.theme": json.dumps(theme), "dalil.did": device}
    if ai:
        seed["dalil.ai.v1"] = json.dumps(ai)
    if convs:
        seed["dalil.convs.v1"] = json.dumps(convs)
    ctx.add_init_script(f"if (!sessionStorage.getItem('seeded')) {{ const s = {json.dumps(seed)};"
                        "localStorage.clear(); for (const k in s) localStorage.setItem(k, s[k]); sessionStorage.setItem('seeded', 1); }"
                        + init_script)
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())
    return ctx, pg


def open_home(pg: Page):
    pg.goto(BASE + "/")
    pg.wait_for_selector(".hero h1")
    pg.wait_for_function("document.querySelector('.aichip .lbl')?.textContent.includes('/') || document.querySelector('.aichip .lbl')?.textContent.includes('·')", timeout=10000)
    pg.wait_for_timeout(600)


def ask(pg: Page, q: str, timeout=180):
    pg.fill(".composer input", q)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(400)
    pg.wait_for_function("!document.body.classList.contains('busy')", timeout=timeout * 1000)
    # matn bo'sh joygacha ochiladi: qisqa javobning oxirgi "so'zi" ([1][2][3].) biroz keyin chiqadi
    pg.wait_for_timeout(1500)
    pg.wait_for_function("!document.querySelector('.prose .w, .prose .cite.w')", timeout=60000)
    pg.wait_for_timeout(500)


def last_turn(pg: Page) -> dict:
    return pg.evaluate("""() => { const t = [...document.querySelectorAll('.turn')].pop();
      return { head: t?.querySelector('.a-head')?.innerText || '', notice: t?.querySelector('.notice h4')?.innerText || '',
               msg: t?.querySelector('.notice p')?.innerText || '', cites: t?.querySelectorAll('.prose .cite').length || 0,
               text: t?.querySelector('.prose')?.innerText || '' }; }""")


def chip(pg: Page) -> str:
    return pg.inner_text(".aichip .lbl").replace("\n", " ")


# ---------------------------------------------------------------- bosqichlar
def phase_api():
    c = httpx.Client(base_url=BASE, timeout=60)
    h = c.get("/api/health").json()
    ok(h["llm"]["configured"], "server kaliti bor (bepul rejim)", f"model={h['llm']['model']}")
    ok(h["free_daily_limit"] == 2, "FREE_DAILY_LIMIT=2 (sinov)")
    q = c.get("/api/quota", headers={"X-Device-Id": "api-check-0001"}).json()
    ok(q == {"limit": 2, "used": 0, "left": 2, "reason": None, "free": True}, "/api/quota yangi qurilma", str(q))
    r = c.post("/api/context", json={"question": Q1}).json()
    ok(r["sources"] and r["prompt"] and "MANBALAR" in r["prompt"]["user"] and "[1]" in r["prompt"]["user"],
       "/api/context: manbalar + tayyor so'rov", f"{len(r['sources'])} manba, user prompt {len(r['prompt']['user'])} belgi")
    sys.path.insert(0, str(ROOT))
    from lexrag import rag
    ok(r["prompt"]["system"] == rag.SYSTEM, "/api/context system prompt rag.SYSTEM bilan bir xil")
    # "topilmadi": eng yaqin modda ham uzoq (cosine < NO_ANSWER_COS) bo'lsa prompt berilmaydi
    r = c.post("/api/context", json={"question": "qwrtpsdfg zxcvbnm hjklqwe"}).json()
    best = max((s["cosine"] or 0) for s in r["sources"]) if r["sources"] else 0
    ok((r["prompt"] is None) == (best < rag.NO_ANSWER_COS) and r["no_answer"] == (best < rag.NO_ANSWER_COS),
       "/api/context: no_answer mantiqi rag.prepare bilan bir xil", f"best cosine={best:.3f}, no_answer={r['no_answer']}")
    r = c.post("/api/proxy/openai/chat/completions", json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "Salom"}]},
               headers={"Authorization": f"Bearer {FAKE['openai']}"})
    ok(r.status_code == 401 and "invalid_api_key" in r.text, "OpenAI proksisi: soxta kalit -> 401 invalid_api_key (CORS'siz ham o'qiladi)")


def phase_free(b):
    global llm_calls
    ctx, pg = new_page(b, DESK, DEV_DESK)
    asks = []
    pg.on("request", lambda r: asks.append(r.url) if r.url.endswith("/api/ask") else None)
    open_home(pg)
    ok("2/2" in chip(pg), "desktop: 'Bugun 2/2 bepul savol qoldi'", chip(pg))
    shot(pg, "desktop-1-bosh")
    for i, q in enumerate((Q1, Q2), 1):
        llm_calls += 1
        t0 = time.time()
        ask(pg, q)
        t = last_turn(pg)
        ok(t["cites"] > 0 and not t["notice"], f"bepul savol {i}: javob oqimi + [n] iqtiboslar",
           f"{time.time() - t0:.0f}s, {t['head']}, iqtibos={t['cites']}, xato={t['notice'] or '-'} {t['msg'][:120]}")
        ok(f"{2 - i}/2" in chip(pg), f"chip {2 - i}/2 ga tushdi", chip(pg))
        if i == 1:
            pg.evaluate("document.querySelector('.scroll').scrollTop = 0")
            pg.wait_for_timeout(300)
            shot(pg, "desktop-2-javob-bepul")
    CONVS.write_text(pg.evaluate("localStorage.getItem('dalil.convs.v1')"))
    n = len(asks)
    pg.fill(".composer input", Q3)
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".modal-wrap.open .limit", timeout=5000)
    pg.wait_for_timeout(700)
    ok(len(asks) == n, "3-savol: limit oynasi, serverga so'rov yuborilmadi")
    ok(pg.input_value(".composer input") == Q3, "3-savol matni kompozerda saqlanib qoldi")
    ok("aistudio.google.com/apikey" in pg.inner_html(".modal-wrap.open"), "limit oynasida Gemini kalit yo'riqnomasi + havola")
    shot(pg, "desktop-3-limit")
    pg.click(".modal-wrap.open .limit .primary")
    pg.wait_for_selector(".modal-wrap.open .ai-form")
    pg.wait_for_timeout(700)
    shot(pg, "desktop-4-ai-ulash")
    # server ham cheklaydi (eski holatdagi mijoz chetlab o'tolmaydi)
    r = httpx.post(BASE + "/api/ask", json={"question": Q3}, headers={"X-Device-Id": DEV_DESK}, timeout=60)
    ev = sse_events(r.text)
    err = [d for e, d in ev if e == "error"]
    ok(err and err[0]["code"] == "free_limit" and any(e == "sources" for e, _ in ev),
       "server: limitdan keyin /api/ask -> sources + free_limit (LLM chaqirilmadi)", err[0]["message"][:90] if err else r.text[:200])
    ctx.close()


def check_key(pg: Page, provider: str, key: str) -> str:
    idx = {"gemini": 0, "openai": 1, "anthropic": 2}[provider]
    pg.click(f".ai-form .seg3 button >> nth={idx}")
    pg.fill(".keyrow input", key)
    pg.click(".ai-form .primary")
    pg.wait_for_timeout(300)
    pg.wait_for_function("!document.querySelector('.ai-status.tone-wait')", timeout=30000)
    pg.wait_for_timeout(900)  # holat kartochkasiga silliq aylantirish
    return pg.inner_text(".ai-status").replace("\n", " | ")


def phase_keys(b):
    ctx, pg = new_page(b, DESK, "e2e-keys-0001")
    leaks = []

    def watch(r):
        if not r.url.startswith(BASE):
            return
        # yagona istisno: OpenAI proksisi, kalit faqat Authorization sarlavhasida
        hdrs = {k: v for k, v in r.headers.items() if not (k == "authorization" and "/api/proxy/openai/" in r.url)}
        if any(k in (r.post_data or "") + r.url + json.dumps(hdrs) for k in FAKE.values()):
            leaks.append(r.url)
    pg.on("request", watch)
    open_home(pg)
    pg.click(".hero-composer .aichip")
    pg.wait_for_selector(".modal-wrap.open .ai-form")
    for p in ("gemini", "openai", "anthropic"):
        s = check_key(pg, p, FAKE[p])
        ok("Kalit qabul qilinmadi" in s, f"{p}: soxta kalit -> 'kalit qabul qilinmadi' (brauzerdan haqiqiy so'rov, CORS ishladi)", s)
        if p == "gemini":
            shot(pg, "desktop-5-notogri-kalit")
    ok(pg.evaluate("localStorage.getItem('dalil.ai.v1')") is None, "noto'g'ri kalit saqlanmadi")
    ok(not leaks, "kalit Dalil serveriga yuborilmadi (OpenAI: faqat proksi sarlavhasida)", ", ".join(leaks))
    ctx.close()


def phase_byok(b):
    ai = {"provider": "gemini", "model": "gemini-3.5-flash", "key": FAKE["gemini"], "status": "unchecked"}
    ctx, pg = new_page(b, DESK, "e2e-byok-0001", ai=ai)
    seen = []
    pg.on("request", lambda r: seen.append(r.url))
    open_home(pg)
    ok("Gemini · gemini-3.5-flash" in chip(pg), "o'z kaliti: chip provayder va modelni ko'rsatadi", chip(pg))
    ask(pg, Q1, timeout=60)
    t = last_turn(pg)
    ok(any(u.endswith("/api/context") for u in seen) and not any(u.endswith("/api/ask") for u in seen),
       "o'z kaliti: /api/context ishlatildi, /api/ask (server kaliti) yo'q")
    ok(any("generativelanguage.googleapis.com" in u and "streamGenerateContent" in u for u in seen), "brauzer Gemini'ga to'g'ridan-to'g'ri oqim so'rovi yubordi")
    ok(t["notice"] == "API kalit notoʻgʻri" and "Gemini kalitingiz" in t["msg"], "noto'g'ri kalit bilan savol: odam tilidagi xato", f"{t['notice']}: {t['msg'][:100]}")
    ok(json.loads(pg.evaluate("localStorage.getItem('dalil.ai.v1')"))["status"] == "bad_key", "kalit holati 'bad_key' ga o'tdi")
    ok("kalit xato" in chip(pg), "chip: 'kalit xato'", chip(pg))
    shot(pg, "desktop-6-byok-xato")
    ctx.close()


def mock_sse(lines: list[str]) -> str:
    return "".join(f"data: {x}\n\n" for x in lines)


def phase_mock(b):
    """Faqat parser: provayder javobi soxta (route.fulfill). Haqiqiy kalit bilan oqim sinalmagan."""
    cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "POST, OPTIONS"}
    text = "Yillik asosiy taʼtil kamida 21 kalendar kun [1]. "
    seen_headers = {}

    def handler(provider):
        def h(route):
            req = route.request
            if req.method == "OPTIONS":
                return route.fulfill(status=204, headers=cors)
            seen_headers[provider] = dict(req.headers)
            if provider == "gemini" and "gemini-3.5-flash" in req.url:  # birinchi model band -> zaxiraga o'tish
                return route.fulfill(status=503, headers=cors, body='{"error":{"code":503,"status":"UNAVAILABLE"}}')
            body = {
                "gemini": mock_sse([json.dumps({"candidates": [{"content": {"parts": [{"text": "fikrlash", "thought": True}]}}]}),
                                    json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}),
                                    json.dumps({"candidates": [{"content": {"parts": [{"text": "Batafsil [2]."}]}, "finishReason": "STOP"}]})]),
                "openai": mock_sse([json.dumps({"choices": [{"delta": {"content": text}}]}),
                                    json.dumps({"choices": [{"delta": {"content": "Batafsil [2]."}}]}), "[DONE]"]),
                "anthropic": "event: message_start\n" + mock_sse([json.dumps({"type": "message_start"})])
                             + mock_sse([json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}),
                                         json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Batafsil [2]."}}),
                                         json.dumps({"type": "message_stop"})]),
            }[provider]
            route.fulfill(status=200, headers={**cors, "Content-Type": "text/event-stream"}, body=body)
        return h

    for provider, model, url in (("gemini", "gemini-3.5-flash", "https://generativelanguage.googleapis.com/**"),
                                 ("openai", "gpt-4.1-mini", "**/api/proxy/openai/**"),
                                 ("anthropic", "claude-haiku-5-5", "https://api.anthropic.com/**")):
        ai = {"provider": provider, "model": model, "key": FAKE[provider], "status": "ok"}
        ctx, pg = new_page(b, DESK, "e2e-mock-0001", ai=ai)
        pg.route(url, handler(provider))
        open_home(pg)
        ask(pg, Q1, timeout=60)
        t = last_turn(pg)
        want_model = "gemini-3.1-flash-lite" if provider == "gemini" else model
        ok(t["cites"] == 2 and "fikrlash" not in t["text"] and want_model in t["head"],
           f"mock {provider}: oqim parseri, [n] tugmalari" + (", 503 -> zaxira model" if provider == "gemini" else ""), t["head"])
        ctx.close()
    hd = seen_headers.get("anthropic", {})
    ok(hd.get("anthropic-dangerous-direct-browser-access") == "true" and hd.get("x-api-key") == FAKE["anthropic"],
       "Anthropic: brauzer sarlavhasi anthropic-dangerous-direct-browser-access: true")
    ok(seen_headers.get("gemini", {}).get("x-goog-api-key") == FAKE["gemini"], "Gemini: kalit x-goog-api-key sarlavhasida (URL'da emas)")


def tg_script(init: str, cloud: dict) -> str:
    return ("window.__cs = " + json.dumps(cloud) + ";"
            "window.Telegram = { WebApp: { initData: " + json.dumps(init) + ", colorScheme: 'light', viewportStableHeight: 844,"
            " ready(){}, expand(){}, onEvent(){}, isVersionAtLeast: () => true, setHeaderColor(){}, setBackgroundColor(){}, setBottomBarColor(){},"
            " BackButton: { show(){}, hide(){}, onClick(){}, offClick(){} }, HapticFeedback: { impactOccurred(){} },"
            " CloudStorage: { setItem(k, v, cb) { __cs[k] = v; cb && cb(null, true); }, getItem(k, cb) { cb(null, __cs[k] || ''); },"
            " removeItem(k, cb) { delete __cs[k]; cb && cb(null, true); } } } };")


def phase_tg(b):
    c = httpx.Client(base_url=BASE, timeout=30)
    good = signed_init_data(777)
    q1 = c.get("/api/quota", headers={"X-Device-Id": DEV_DESK, "X-Telegram-Init-Data": good}).json()
    q2 = c.get("/api/quota", headers={"X-Device-Id": DEV_DESK, "X-Telegram-Init-Data": good.replace("777", "778")}).json()
    ok(q1["left"] == 2, "Telegram: imzosi to'g'ri initData -> alohida foydalanuvchi (tg:777)", str(q1))
    ok(q2["left"] == 0, "Telegram: soxtalashtirilgan initData -> qurilma ID bo'yicha (limiti tugagan)", str(q2))
    # Mini App: kalit CloudStorage'dan yuklanadi va o'chiriladi (Telegram obyekti sinov uchun soxta)
    cfg = {"provider": "openai", "model": "gpt-4.1-mini", "key": FAKE["openai"], "status": "ok"}
    ctx, pg = new_page(b, MOB, "e2e-tg-000001", init_script=tg_script(good, {"dalil_ai_v1": json.dumps(cfg)}))
    pg.route("https://telegram.org/**", lambda r: r.fulfill(status=200, body="", content_type="application/javascript"))
    hdrs = []
    pg.on("request", lambda r: hdrs.append(r.headers.get("x-telegram-init-data", "")) if r.url.endswith("/api/quota") else None)
    open_home(pg)
    ok("OpenAI · gpt-4.1-mini" in chip(pg), "Telegram: kalit CloudStorage'dan yuklandi", chip(pg))
    ok(json.loads(pg.evaluate("localStorage.getItem('dalil.ai.v1')") or "{}").get("provider") == "openai", "CloudStorage -> localStorage zaxira nusxa")
    ok(any(hdrs), "Telegram: /api/quota so'roviga initData sarlavhasi qo'shildi")
    pg.click(".aichip")
    pg.wait_for_selector("#sh-ai[aria-hidden='false'] .ai-form")
    pg.wait_for_timeout(700)
    pg.click("#sh-ai .linkbtn.danger")
    pg.wait_for_timeout(500)
    ok(pg.evaluate("Object.keys(window.__cs).length") == 0 and pg.evaluate("localStorage.getItem('dalil.ai.v1')") is None,
       "'Kalitni o'chirish': CloudStorage va localStorage tozalandi")
    ctx.close()


def phase_mobile(b):
    convs = json.loads(CONVS.read_text()) if CONVS.exists() else None
    ctx, pg = new_page(b, MOB, DEV_MOB)
    open_home(pg)
    ok("2/2" in chip(pg), "mobil: bosh sahifada bepul limit chipi", chip(pg))
    shot(pg, "mobile-1-bosh")
    ctx.close()
    # limiti tugagan qurilma + desktopdagi suhbat (LLM qayta chaqirilmaydi)
    ctx, pg = new_page(b, MOB, DEV_DESK, convs=convs)
    open_home(pg)
    if convs:
        pg.click(".nav .cbtn")
        pg.wait_for_timeout(700)
        pg.click("#sh-history .hlist .row >> nth=0")
        pg.wait_for_timeout(900)
        pg.evaluate("document.querySelector('.scroll').scrollTop = 1e6")
        pg.wait_for_timeout(400)
        ok("0/2" in chip(pg), "mobil: javobdan keyin 'Bugun 0/2'", chip(pg))
        shot(pg, "mobile-2-javob-bepul")
    pg.fill(".composer input", Q3)
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#sh-limit[aria-hidden='false'] .limit")
    pg.wait_for_timeout(900)
    ok(True, "mobil: limit varag'i ochildi")
    shot(pg, "mobile-3-limit")
    pg.click("#sh-limit .limit .primary")
    pg.wait_for_selector("#sh-ai[aria-hidden='false'] .ai-form")
    pg.wait_for_timeout(900)
    shot(pg, "mobile-4-ai-ulash")
    s = check_key(pg, "gemini", FAKE["gemini"])
    ok("Kalit qabul qilinmadi" in s, "mobil: soxta Gemini kalit xatosi", s)
    shot(pg, "mobile-5-notogri-kalit")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(700)
    pg.click(".nav .cbtn")
    pg.wait_for_timeout(900)
    pg.evaluate("document.querySelector('#sh-history .sh-body').scrollTop = 1e6")
    pg.wait_for_timeout(300)
    shot(pg, "mobile-6-sozlamalar")
    ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="api,free,keys,byok,mock,tg,mobile")
    ap.add_argument("--dist", default="/tmp/dalil-byok-dist")
    ap.add_argument("--fresh-quota", action="store_true", help="kvota hisoblagichini nolga tushirish")
    a = ap.parse_args()
    only = a.only.split(",")
    db = Path("/tmp/dalil-test-quota.sqlite")
    if a.fresh_quota:
        for p in db.parent.glob(db.name + "*"):
            p.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = Path("/tmp/dalil-e2e-server.log")
    log = log_path.open("w")
    srv = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "test_server.py"), "--port", str(PORT), "--free-limit", "2",
                            "--dist", a.dist, "--quota-db", str(db), "--telegram-token", TG_TOKEN],
                           stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                if httpx.get(BASE + "/api/health", timeout=2).json().get("index_ready"):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1)
        else:
            raise SystemExit("Sinov serveri ishga tushmadi: /tmp/dalil-e2e-server.log")
        print(f"Sinov serveri tayyor: {BASE}\n", flush=True)
        if "api" in only:
            phase_api()
        with sync_playwright() as p:
            b = p.chromium.launch()
            for name, fn in (("free", phase_free), ("keys", phase_keys), ("byok", phase_byok), ("mock", phase_mock),
                             ("tg", phase_tg), ("mobile", phase_mobile)):
                if name in only:
                    print(f"\n--- {name}", flush=True)
                    try:
                        fn(b)
                    except Exception as e:  # noqa: BLE001
                        ok(False, f"{name} bosqichi yiqildi", f"{type(e).__name__}: {str(e)[:300]}")
            b.close()
    finally:
        srv.terminate()
        srv.wait(10)
        log.close()
    text = log_path.read_text(errors="replace")
    ok(not any(k in text for k in FAKE.values()), "server logida kalit yo'q", f"{len(text.splitlines())} qator log")
    bad = [n for c, n in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} o'tdi; server kaliti bilan LLM savollari: {llm_calls}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
