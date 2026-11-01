"""Internetga chiqarish sinovi: production rejimidagi server (Docker konteyner yoki unga teng lokal jarayon).

    # 1) Docker'siz: konteynerdagi kabi muhit (ENV=production, bo'sh data papkasi -> seed'dan nusxa, model offline)
    .venv/bin/python scripts/hf_deploy.py --dry-run --stage /tmp/dalil-space --stage-data /tmp/dalil-seed
    cd web && npx vite build --outDir /tmp/dalil-deploy-dist --emptyOutDir && cd ..
    .venv/bin/python scripts/deploy_e2e.py --spawn --ask ui

    # 2) Docker konteyner (7861-portda ishlab turibdi):
    .venv/bin/python scripts/deploy_e2e.py --url http://127.0.0.1:7861 --container dalil-test --ask api

Tekshiriladi: port ochilish va "ready" vaqti, yuklanish paytidagi /api/health "loading" va "Tayyorlanmoqda…" chipi,
xavfsizlik sarlavhalari, /api/search, bitta haqiqiy savol (--ask api|ui|none, aynan 1 ta LLM so'rovi), CSP sahifani
buzmagani (Playwright: konsol xatolari, desktop + mobil skrinshot design/shots/app/deploy-*.png), rate limit (429),
xotira (RSS yoki docker stats). 8000-portdagi serverga tegmaydi.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "design" / "shots" / "app"
results: list[tuple[bool, str]] = []
REPORT: dict = {}


def ok(c, name, detail=""):
    results.append((bool(c), name))
    print(("  ok  " if c else "  XATO") + f" {name}" + (f" - {detail}" if detail and not c else ""), flush=True)


def rss_mb(pid: int) -> float | None:
    """Jarayon va bolalari RSS (MB)."""
    try:
        out = subprocess.run(["ps", "-o", "rss=,ppid=,pid=", "-A"], capture_output=True, text=True).stdout
    except OSError:
        return None
    rows = [tuple(map(int, l.split())) for l in out.splitlines() if l.strip()]
    kids, total, stack = {}, 0, [pid]
    for rss, ppid, p in rows:
        kids.setdefault(ppid, []).append((p, rss))
    me = {p: rss for rss, _, p in rows}
    seen = set()
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        total += me.get(p, 0)
        stack += [c for c, _ in kids.get(p, [])]
    return round(total / 1024, 1)


def docker_mem(name: str) -> str | None:
    try:
        return subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}} | CPU {{.CPUPerc}}", name],
                              capture_output=True, text=True, timeout=60).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def spawn(port: int, data_dir: str, seed: str, dist: str) -> subprocess.Popen:
    env = {**os.environ, "PATH": f"{ROOT / '.venv' / 'bin'}:{os.environ.get('PATH', '')}", "PORT": str(port),
           "ENV": "production", "TRUST_PROXY": "1", "DALIL_DATA_DIR": data_dir, "DALIL_SEED_DIR": seed,
           "DALIL_MODELS_DIR": str(ROOT / ".models"), "DALIL_MODEL_OFFLINE": "1", "DALIL_DIST": dist,
           "ANONYMIZED_TELEMETRY": "False", "PYTHONUNBUFFERED": "1"}
    env.pop("DALIL_QUOTA_DB", None)
    log = open("/tmp/dalil-deploy-e2e.log", "w")
    # start.sh - konteynerdagi bilan aynan bir xil buyruq (ma'lumotlar papkasi, quota yo'li, uvicorn bayroqlari)
    return subprocess.Popen(["sh", str(ROOT / "deploy" / "hf-space" / "start.sh")], cwd=ROOT, env=env,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def wait_port(base: str, t0: float, timeout=300, proc: subprocess.Popen | None = None) -> float | None:
    while time.time() - t0 < timeout:
        if proc is not None and proc.poll() is not None:
            return None
        try:
            httpx.get(base + "/api/health", timeout=2)
            return time.time() - t0
        except httpx.HTTPError:
            time.sleep(0.2)
    return None


def phase_boot(base: str, t0: float, pw_browser, proc=None) -> dict:
    t_port = wait_port(base, t0, proc=proc)
    ok(t_port is not None, "port ochildi", "300 s ichida javob yo'q")
    if t_port is None:
        return {}
    REPORT["port_open_s"] = round(t_port, 1)
    h = httpx.get(base + "/api/health", timeout=5).json()
    print(f"    port {t_port:.1f} s da ochildi; health: status={h.get('status')} phase={h.get('phase')}")
    if h.get("status") == "loading":
        ok(True, "yuklanish paytida /api/health status=loading")
        r = httpx.get(base + "/api/search", params={"q": "taʼtil"}, timeout=10)
        ok(r.status_code == 503 and r.json().get("code") == "loading", "yuklanish paytida /api/search -> 503 loading")
        if pw_browser:
            ctx = pw_browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                                         has_touch=True)
            pg = ctx.new_page()
            pg.goto(base + "/", wait_until="domcontentloaded")
            try:
                pg.wait_for_selector(".bootchip", timeout=8000)
                ok(True, "frontend: \"Tayyorlanmoqda…\" chipi ko'rindi")
                pg.wait_for_timeout(600)
                pg.screenshot(path=str(OUT / "deploy-mobile-0-tayyorlanmoqda.png"))
            except Exception:  # noqa: BLE001
                ok(False, "frontend: \"Tayyorlanmoqda…\" chipi ko'rindi", "server juda tez tayyor bo'ldi yoki chip yo'q")
            ctx.close()
    phases, worst = [], 0.0
    while time.time() - t0 < 600:
        # bge-m3 ONNX sessiyasi yaratilayotganda onnxruntime GIL'ni ushlaydi: health bir necha soniya kechikadi
        tq = time.time()
        h = httpx.get(base + "/api/health", timeout=120).json()
        worst = max(worst, time.time() - tq)
        if not phases or phases[-1] != h.get("phase"):
            phases.append(h.get("phase"))
        if h.get("status") != "loading":
            break
        time.sleep(0.5)
    t_ready = time.time() - t0
    REPORT["ready_s"] = round(t_ready, 1)
    REPORT["phases"] = phases
    REPORT["health_max_latency_s"] = round(worst, 1)
    ok(h.get("status") == "ready", f"server tayyor: {t_ready:.1f} s, bosqichlar {' -> '.join(map(str, phases))}",
       json.dumps(h, ensure_ascii=False)[:300])
    return h


def phase_api(base: str, ask: bool):
    r = httpx.get(base + "/")
    hs = r.headers
    ok("frame-ancestors" in hs.get("content-security-policy", "") and "x-frame-options" not in hs,
       "/: CSP bor, X-Frame-Options yo'q")
    ok(hs.get("x-content-type-options") == "nosniff" and "microphone=(self)" in hs.get("permissions-policy", ""),
       "/: nosniff, Permissions-Policy")
    asset = next((l.split('"')[0] for l in r.text.split('src="/assets/')[1:2]), None)
    if asset:
        ok("immutable" in httpx.get(f"{base}/assets/{asset}").headers.get("cache-control", ""), "/assets: immutable kesh")
    ok(httpx.get(base + "/api/docs").status_code in (404, 200) and "swagger" not in httpx.get(base + "/api/docs").text.lower(),
       "/api/docs o'chiq")
    ok(httpx.get(base + "/api/openapi.json").status_code == 404, "/api/openapi.json o'chiq")
    ok(httpx.post(base + "/api/eval/run").status_code == 403, "/api/eval/run o'chiq (EVAL_TOKEN yo'q)")
    dev = {"x-device-id": "deploye2e-api-1"}
    t = time.time()
    r = httpx.get(base + "/api/search", params={"q": "Yillik mehnat taʼtilining eng kam muddati", "k": 5}, headers=dev, timeout=60)
    REPORT["search_ms"] = int((time.time() - t) * 1000)
    res = r.json().get("results", []) if r.status_code == 200 else []
    ok(r.status_code == 200 and res, f"/api/search: {len(res)} natija, {REPORT['search_ms']} ms",
       f"{r.status_code} {r.text[:200]}")
    if res:
        print(f"    1-natija: {res[0].get('doc_title', '')[:60]} · {res[0].get('article_number')}-modda")
    if not ask:
        return
    q = {"question": "Yillik mehnat taʼtilining eng kam muddati necha kun?"}
    t = time.time()
    ev, text = {}, ""
    with httpx.stream("POST", base + "/api/ask", json=q, headers={**dev, "origin": base}, timeout=180) as s:
        cur = None
        for line in s.iter_lines():
            if line.startswith("event:"):
                cur = line[6:].strip()
            elif line.startswith("data:") and cur:
                d = json.loads(line[5:])
                ev.setdefault(cur, []).append(d)
                if cur == "delta":
                    text += d.get("text", "")
    REPORT["ask_s"] = round(time.time() - t, 1)
    done = (ev.get("done") or [{}])[-1]
    ok("done" in ev and text.strip(), f"/api/ask (1 ta LLM so'rovi): {REPORT['ask_s']} s, model {done.get('model')}",
       json.dumps(ev.get("error"), ensure_ascii=False)[:300])
    print(f"    javob: {text.strip()[:160].replace(chr(10), ' ')}…")


def phase_ui(base: str, browser, ask_ui: bool):
    for name, vp in (("desktop", {"width": 1440, "height": 900}), ("mobile", {"width": 390, "height": 844})):
        ctx = browser.new_context(viewport=vp, device_scale_factor=2 if name == "mobile" else 1,
                                  is_mobile=name == "mobile", has_touch=name == "mobile")
        pg = ctx.new_page()
        errs: list[str] = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="networkidle")
        pg.wait_for_selector(".hero h1", timeout=15000)
        pg.wait_for_timeout(800)
        theme = pg.evaluate("document.documentElement.dataset.theme")
        ok(theme in ("light", "dark"), f"{name}: boot.js ishladi (tema {theme})")
        # Runtime.evaluate CSP'ga bo'ysunmaydi; wait_for_function esa sahifada eval qiladi - CSP uni (to'g'ri) bloklaydi
        font = pg.evaluate("document.fonts.load('600 16px Onest').then(f => f.length)")
        ok(font > 0, f"{name}: Onest shrifti yuklandi (CSP fonts.googleapis/gstatic)", str(font))
        pg.screenshot(path=str(OUT / f"deploy-{name}-1-bosh.png"))
        if ask_ui and name == "desktop":
            pg.fill('input[aria-label="Savol"]', "Prezident qancha muddatga saylanadi?")
            pg.keyboard.press("Enter")
            js = "document.querySelectorAll('.prose').length > 0 && !document.body.classList.contains('busy')"
            end = time.time() + 180
            pg.wait_for_timeout(1500)
            while time.time() < end and not pg.evaluate(js):
                pg.wait_for_timeout(500)
            pg.wait_for_timeout(2500)  # ishonch tekshiruvi (/api/verify) va animatsiya
            prose = pg.inner_text(".prose")
            cites = pg.locator(".prose .cite").count()
            ok(len(prose) > 40 and cites > 0, f"UI savol (1 ta LLM so'rovi): {len(prose)} belgi, {cites} ta [n]", prose[:200])
            if cites:
                pg.locator(".prose .cite").first.click()
                pg.wait_for_timeout(500)
            pg.screenshot(path=str(OUT / "deploy-desktop-2-javob.png"))
        ok(not errs, f"{name}: konsolda xato yo'q (CSP)", " | ".join(errs)[:500])
        ctx.close()


def phase_rate(base: str):
    """RATE_LIMIT_PER_MIN (standart 20): bitta qurilmadan 25 ta tez so'rov -> oxirgilari 429."""
    dev = {"x-device-id": "deploye2e-rate-1"}
    codes = []
    for _ in range(25):
        codes.append(httpx.get(base + "/api/search", params={"q": "a", "k": 1}, headers=dev, timeout=60).status_code)
    n429 = codes.count(429)
    first = codes.index(429) + 1 if n429 else None
    REPORT["rate_first_429"] = first
    ok(n429 > 0 and all(c == 200 for c in codes[: first - 1]), f"rate limit: {first}-so'rovda 429 ({n429} ta 429)", str(codes))
    r = httpx.get(base + "/api/search", params={"q": "a"}, headers=dev)
    ok(r.json().get("code") == "rate_limit" and r.headers.get("retry-after"), "429 javobi: rate_limit + Retry-After")
    ok(httpx.get(base + "/api/health", headers=dev).status_code == 200, "rate limit health'ga ta'sir qilmaydi")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:7861")
    ap.add_argument("--spawn", action="store_true", help="serverni o'zi ishga tushiradi (Docker'siz, start.sh bilan)")
    ap.add_argument("--container", help="Docker konteyner nomi (docker stats uchun)")
    ap.add_argument("--ask", choices=["api", "ui", "none"], default="none", help="1 ta haqiqiy LLM so'rovi qayerdan")
    ap.add_argument("--data-dir", default="/tmp/dalil-run")
    ap.add_argument("--seed", default="/tmp/dalil-seed")
    ap.add_argument("--dist", default="/tmp/dalil-deploy-dist")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    port = int(base.rsplit(":", 1)[1])
    if port == 8000:
        sys.exit("8000-port - asosiy server, unga tegilmaydi")
    OUT.mkdir(parents=True, exist_ok=True)
    proc = None
    t0 = time.time()
    if a.spawn:
        import shutil
        shutil.rmtree(a.data_dir, ignore_errors=True)  # har safar "yangi konteyner": indeks seed'dan qayta olinadi
        proc = spawn(port, a.data_dir, a.seed, a.dist)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            h = phase_boot(base, t0, b, proc) if a.spawn else httpx.get(base + "/api/health").json()
            if h.get("status") == "ready":
                REPORT["chunks"] = h.get("chunks")
                if proc:
                    REPORT["rss_ready_mb"] = rss_mb(proc.pid)
                phase_api(base, a.ask == "api")
                phase_ui(base, b, a.ask == "ui")
                if proc:
                    REPORT["rss_after_mb"] = rss_mb(proc.pid)
                if a.container:
                    REPORT["docker_stats"] = docker_mem(a.container)
                phase_rate(base)
            b.close()
    finally:
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(20)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
        elif proc:
            print(f"Server o'zi to'xtagan (kod {proc.returncode}), log: /tmp/dalil-deploy-e2e.log")
    print("\nO'lchovlar:", json.dumps(REPORT, ensure_ascii=False))
    bad = [n for c, n in results if not c]
    print(f"{len(results) - len(bad)}/{len(results)} o'tdi")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
