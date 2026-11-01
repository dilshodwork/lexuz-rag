"""3-bosqich e2e: X-ray va /baholash (Playwright). Sinov serveri ishlab turgan bo'lishi kerak:

    cd web && npx vite build --outDir /tmp/dalil-s3-dist --emptyOutDir && cd ..
    .venv/bin/python scripts/test_server.py --port 8010 --free-limit 30 --dist /tmp/dalil-s3-dist \
        --quota-db /tmp/dalil-s3-quota.sqlite --llm-once
    .venv/bin/python scripts/stage3_e2e.py [--only api,mock,real,reshoot,eval]

Bosqichlar:
  api     - LLM'siz: /api/context xray, /api/ask xray hodisasi ("topilmadi" yo'li), /api/eval
  mock    - LLM'siz, brauzerda SOXTA Gemini (route.fulfill): o'z kaliti yo'lida X-ray va LLM vaqtlari
  real    - server kaliti bilan 2 ta HAQIQIY LLM so'rovi (X-ray rejimi yoqiq), desktop yorug' skrinshotlar
  reshoot - LLM'siz: real bosqich suhbatlari localStorage orqali qayta ochiladi: desktop qorong'i, mobil yorug'/qorong'i
  eval    - /baholash: desktop (to'liq sahifa, yorug' + qorong'i), mobil, drilldown, "Qayta hisoblash" (LLM'siz, ~40 s)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from byok_e2e import DESK, MOB, mock_sse, sse_events  # noqa: E402
from stage2_e2e import home, new_page, wait_answer  # noqa: E402

BASE = "http://127.0.0.1:8010"
OUT = ROOT / "design" / "shots" / "app"
CONVS = Path("/tmp/dalil-s3-convs.json")
XRAY_ON = "localStorage.setItem('dalil.xray', 'true');"
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "POST, OPTIONS"}

Q_MIX = "Yillik mehnat taʼtili necha kun va uni qismlarga boʻlish mumkinmi?"
Q_CYR = "Президент неча йилга сайланади?"
Q_RU = "Сколько дней длится ежегодный трудовой отпуск?"
Q_NONE = "qwrtpsdfg zxcvbnm hjklqwe"

results: list[tuple[bool, str]] = []
llm_calls = 0


def ok(cond, name, info=""):
    results.append((bool(cond), name))
    print(f"{'OK  ' if cond else 'XATO'} {name}" + (f" — {info}" if info else ""), flush=True)
    return cond


def shot(page: Page, name: str, full: bool = False):
    p = OUT / f"s3-{name}.png"
    page.screenshot(path=str(p), full_page=full)
    print("     ", p.relative_to(ROOT) if p.is_relative_to(ROOT) else p, flush=True)


def tall(pg: Page, width: int):
    """Ilova ichki scroll'li (#page fixed): to'liq sahifa uchun oyna balandligi kontentga tenglashtiriladi."""
    pg.mouse.move(2, 2)  # hover tooltip skrinshotda qolmasin
    h = pg.evaluate("document.querySelector('.scroll').scrollHeight")
    pg.set_viewport_size({"width": width, "height": int(h) + 10})
    pg.wait_for_timeout(1600)


# ---------------------------------------------------------------- api
def phase_api():
    c = httpx.Client(base_url=BASE, timeout=120)
    r = c.post("/api/context", json={"question": Q_MIX, "xray": True}).json()
    x = r.get("xray") or {}
    s0 = (x.get("searches") or [{}])[0]
    keys = {s["key"] for s in x.get("timeline", [])}
    ok(len(x.get("searches", [])) == 3 and len(x["analysis"]["parts"]) == 2, "/api/context xray: 3 qidiruv (to'liq + 2 qism)", str(x.get("analysis", {}).get("parts")))
    ok(0 < len(s0.get("dense", [])) <= 10 and 0 < len(s0.get("bm25", [])) <= 10 and s0["dense"][0]["cosine"] and s0["bm25"][0]["score"],
       "dense (cosine) va BM25 (ball) top-10 ro'yxatlari", f"dense#1 {s0['dense'][0]}, bm25#1 {s0['bm25'][0]}")
    ok(s0["params"]["w_bm25"] == 0.05 and s0["params"]["rrf_k"] == 60 and all(f["via"] in ("dense", "bm25", "both") for f in s0["fused"]),
       "RRF parametrlari va har manba qaysi usuldan kelgani", json.dumps(s0["params"]))
    ok({"analyze", "embed", "dense", "bm25", "rrf", "fetch", "fuse", "check"} <= keys, "vaqt chizig'i bosqichlari", ", ".join(sorted(keys)))
    ok(x.get("fusion") and x["fusion"]["after"] == len(r["sources"]) and len(x["labels"]) >= len(r["sources"]), "qismlarni birlashtirish va yorliqlar")
    ok(x.get("prompt") and x["prompt"]["tokens"]["total"] > 500 and "system" not in x["prompt"] and r["prompt"]["system"],
       "prompt tokenlari; matn javobning o'zida (takrorlanmaydi)", json.dumps(x.get("prompt", {}).get("tokens")))
    ok(x["threshold"]["no_answer_cos"] == 0.48 and x["threshold"]["best_cos"] > 0.6 and not x["threshold"]["no_answer"], "chegara va eng yaqin cosine", json.dumps(x["threshold"]))
    r2 = c.post("/api/context", json={"question": Q_MIX}).json()
    ok("xray" not in r2, "xray=false: X-ray hisoblanmaydi")
    r3 = c.post("/api/context", json={"question": Q_RU, "xray": True}).json()["xray"]["searches"][0]
    # 4-bosqich: ruscha savol BM25'ga yuborilmaydi (RU_BM25 = "off", DEV'da tanlangan)
    ok(r3["q_dense"] == Q_RU and r3["q_bm25"] == "" and r3["params"]["w_bm25"] == 0 and not r3["bm25"],
       "ruscha savol: dense asl matn, BM25 ishlatilmaydi (4-bosqich)", f"BM25: '{r3['q_bm25'][:60]}' · w={r3['params']['w_bm25']}")
    t = c.post("/api/ask", json={"question": Q_NONE, "xray": True}, headers={"X-Device-Id": "s3-api-0001"}).text
    ev = sse_events(t)
    names = [e for e, _ in ev]
    xe = next((d for e, d in ev if e == "xray"), None)
    ok(xe and names.index("xray") < names.index("done") and xe["threshold"]["no_answer"] and xe["prompt"] is None and xe["llm"]["via"] == "server",
       "/api/ask SSE: xray hodisasi (topilmadi, LLM chaqirilmadi)", " ".join(names))
    e = c.get("/api/eval").json()
    ok(e["results"]["summary"]["hybrid"]["recall@5"] > 0 and e["sweep"]["w_bm25"]["grid"] and e["baseline"] and e["answers"],
       "/api/eval: results, sweep, baseline, answers", f"hybrid R@5 {e['results']['summary']['hybrid']['recall@5']}")


# ---------------------------------------------------------------- mock (o'z kaliti, soxta Gemini)
def phase_mock(b):
    text = "Yillik asosiy taʼtil kamida yigirma bir kalendar kun [1]. Uni qismlarga boʻlish mumkin, bir qismi 14 kundan kam boʻlmasligi kerak [2]."

    def h(route):
        if route.request.method == "OPTIONS":
            return route.fulfill(status=204, headers=CORS)
        time.sleep(0.4)
        body = mock_sse([json.dumps({"candidates": [{"content": {"parts": [{"text": text[:60]}]}}]}),
                         json.dumps({"candidates": [{"content": {"parts": [{"text": text[60:]}]}, "finishReason": "STOP"}]})])
        route.fulfill(status=200, headers={**CORS, "Content-Type": "text/event-stream"}, body=body)
    ai = {"provider": "gemini", "model": "gemini-3.5-flash", "key": "AIza-FAKE-dalil-s3", "status": "ok"}
    ctx, pg = new_page(b, DESK, ai=ai, extra=XRAY_ON)
    pg.route("https://generativelanguage.googleapis.com/**", h)
    home(pg)
    pg.fill(".composer input", Q_MIX)
    pg.keyboard.press("Enter")
    wait_answer(pg, 90)
    pg.wait_for_selector(".inspector .xr")
    d = pg.evaluate("""() => { const i = document.querySelector('.inspector');
      return { secs: i.querySelectorAll('.xr-sec').length, tabs: i.querySelectorAll('.xr-tabs button').length,
        prov: [...i.querySelectorAll('.xr-row')].map(r => r.innerText).find(t => t.startsWith('Provayder')) || '',
        wf: [...i.querySelectorAll('.wf-l')].map(e => e.innerText) }; }""")
    ok(d["secs"] == 5 and d["tabs"] == 3, "o'z kaliti: X-ray paneli avtomatik ochildi (5 bo'lim, 3 qidiruv tabi)")
    ok("Oʻz kalitingiz" in d["prov"] and "Gemini" in d["prov"], "provayder: o'z kaliti (brauzerdan)", d["prov"].replace("\n", " "))
    ok("LLM: birinchi token" in d["wf"] and "LLM: javob oqimi" in d["wf"], "LLM vaqtlari brauzerda o'lchandi (waterfall)", " | ".join(d["wf"]))
    pg.wait_for_timeout(800)
    shot(pg, "xray-byok-mock")  # soxta provayder javobi (nomida "mock")
    ctx.close()


# ---------------------------------------------------------------- real (2 ta LLM so'rovi)
def xr_scroll(pg: Page, sec: str):
    pg.evaluate(f"""(() => {{ const b = document.querySelector('.inspector .sh-body'); const s = b.querySelector('[data-sec="{sec}"]');
      b.scrollTop = s.offsetTop - b.offsetTop - 8; }})()""")
    pg.wait_for_timeout(500)


def phase_real(b):
    global llm_calls
    ctx, pg = new_page(b, DESK, extra=XRAY_ON)
    home(pg)
    for q in (Q_MIX, Q_CYR):
        llm_calls += 1
        pg.fill(".composer input", q)
        pg.keyboard.press("Enter")
        wait_answer(pg, 200)
        err = pg.evaluate("document.querySelector('.turn:last-child .notice.err, .turn:last-child .notice.key')?.innerText || ''")
        ok(not err, f"haqiqiy javob: {q}", err[:160])
        if q == Q_MIX:
            pg.wait_for_function("[...document.querySelectorAll('.inspector .wf-l')].some(e => e.innerText.includes('javob oqimi'))", timeout=20000)
            d = pg.evaluate("""() => { const i = document.querySelector('.inspector');
              return { model: [...i.querySelectorAll('.xr-row')].map(r => r.innerText).find(t => t.startsWith('Model')) || '',
                       wf: [...i.querySelectorAll('.wf-row')].map(e => e.innerText.replace(/\\n/g, ' ')) }; }""")
            ok("gemini" in d["model"].lower(), "server yo'li: model X-ray'da", d["model"].replace("\n", " "))
            ok(any("birinchi token" in w for w in d["wf"]), "server yo'li: LLM birinchi token va oqim vaqti", " | ".join(d["wf"][-4:]))
            pg.wait_for_timeout(800)
            shot(pg, "xray-desktop-light")
            xr_scroll(pg, "t")
            shot(pg, "xray-desktop-timeline")
            xr_scroll(pg, "q")
    CONVS.write_text(pg.evaluate("localStorage.getItem('dalil.convs.v1')"), encoding="utf-8")
    ctx.close()


# ---------------------------------------------------------------- reshoot (LLM'siz)
def phase_reshoot(b):
    convs = CONVS.read_text(encoding="utf-8")
    ctx, pg = new_page(b, DESK, theme="dark", convs=convs)
    home(pg)
    pg.click(".side .hist >> nth=0")
    pg.wait_for_selector(".turn")
    pg.wait_for_timeout(600)
    pg.click(".turn >> nth=0 >> .xr-btn")
    pg.wait_for_selector(".inspector .xr")
    pg.wait_for_timeout(900)
    tok = pg.evaluate("[...document.querySelectorAll('.inspector .xr-sum span')].map(e => e.innerText).join(' · ')")
    ok("token" in tok, "saqlangan suhbatda X-ray (prompt matnisiz, token soni bor)", tok)
    shot(pg, "xray-desktop-dark")
    ctx.close()
    for theme in ("light", "dark"):
        ctx, pg = new_page(b, MOB, theme=theme, convs=convs)
        home(pg)
        pg.click(".nav .cbtn >> nth=0")
        pg.wait_for_timeout(700)
        pg.click("#sh-history .hlist .row >> nth=0")
        pg.wait_for_selector(".turn")
        pg.wait_for_timeout(700)
        pg.evaluate("document.querySelector('.turn .xr-btn').scrollIntoView({block: 'center'})")
        pg.click(".turn >> nth=0 >> .xr-btn")
        pg.wait_for_selector("#sh-xray .xr")
        pg.wait_for_timeout(1100)
        if theme == "dark":  # qidiruv bo'limi ko'rinsin
            pg.evaluate("(() => { const b = document.querySelector('#sh-xray .sh-body'); const s = b.querySelector('[data-sec=\"s\"]'); b.scrollTop = s.offsetTop - 60; })()")
            pg.wait_for_timeout(500)
        ok(pg.is_visible("#sh-xray .xr-sec"), f"mobil X-ray varag'i ({theme})")
        shot(pg, f"xray-mobile-{theme}")
        ctx.close()


# ---------------------------------------------------------------- baholash sahifasi
def phase_eval(b):
    res = httpx.get(BASE + "/api/eval", timeout=30).json()["results"]
    # 4-bosqich: sahifa standart holatda TEST qismini ko'rsatadi (by_split bo'lsa)
    blk = (res.get("by_split") or {}).get("test") or {"summary": res["summary"], "n_questions": res["meta"]["n_questions"]}
    qs = [q for q in res["questions"] if q.get("split", "test") == "test"] if res.get("by_split") else res["questions"]
    want = f"{blk['summary']['hybrid']['recall@5'] * 100:.1f}".replace(".", ",") + "%"
    thr = res["meta"]["params"]["NO_ANSWER_COS"]
    n_miss = 0
    for q in qs:
        h = q["modes"]["hybrid"]
        n_miss += ((h["best_cos"] or 1) >= thr) if not q["answerable"] else (not h["metrics"]["rank"] or h["metrics"]["rank"] > 5)

    for theme in ("light", "dark"):
        ctx, pg = new_page(b, DESK, theme=theme)
        pg.goto(BASE + "/baholash")
        pg.wait_for_selector(".ev-kpis .kpi-v")
        pg.wait_for_timeout(2200)
        if theme == "light":
            kpi = pg.inner_text(".ev-kpis .kpi-v >> nth=0")
            ok(kpi == want, "KPI recall@5 results.json bilan bir xil", f"{kpi} = {want}")
            rows = pg.locator(".ev-tbl:not(.small) tbody tr").count()
            ok(rows == len(qs), "har savol jadvali (TEST)", f"{rows} qator")
            ok(pg.locator(".ch svg").count() >= 5 and pg.locator(".hm-c").count() > 10, "grafiklar chizildi (ustun, chiziq, issiqlik xaritasi, sweep, taqsimot)")
            pg.hover(".bar-g >> nth=10")
            pg.wait_for_timeout(300)
            ok(pg.is_visible(".ch-tip"), "hover tooltip")
        tall(pg, 1440)
        shot(pg, f"eval-desktop{'-dark' if theme == 'dark' else ''}", full=True)
        if theme == "light":
            pg.set_viewport_size({"width": 1440, "height": 900})
            pg.wait_for_timeout(500)
            pg.click(".ev-sw .sw")
            pg.wait_for_timeout(400)
            rows = pg.locator(".ev-tbl:not(.small) tbody tr").count()
            ok(rows == n_miss, "“Faqat xatolar” filtri", f"{rows} ta (kutilgan {n_miss})")
            pg.click(".ev-tbl:not(.small) tbody tr >> nth=0")
            pg.wait_for_selector(".modal-wrap.open .drill")
            pg.wait_for_timeout(700)
            d = pg.inner_text(".modal-wrap.open .drill")
            ok("Nomzodlar roʻyxatida" in d or "chegara" in d, "drilldown: gold o'rni, dense/BM25 da topilgani", d[:120].replace("\n", " "))
            shot(pg, "eval-drill-desktop")
            pg.keyboard.press("Escape")
            pg.click(".modal-wrap.open .sh-close") if pg.is_visible(".modal-wrap.open") else None
            # Qayta hisoblash (LLM'siz) - progress
            pg.evaluate("document.querySelector('.scroll').scrollTo({top: 0})")
            pg.click(".ev-run")
            pg.wait_for_selector(".ev-prog", timeout=10000)
            pg.wait_for_timeout(5000)
            busy = httpx.post(BASE + "/api/eval/run", timeout=10)
            ok(busy.status_code == 409, "bir vaqtda faqat bitta baholash (409)", str(busy.status_code))
            shot(pg, "eval-running")
            pg.wait_for_selector(".ev-prog", state="detached", timeout=240000)
            pg.wait_for_timeout(1500)
            st = httpx.get(BASE + "/api/eval/status").json()
            ok(not st["running"] and not st["error"] and st["done"] == st["total"] == res["meta"]["n_questions"], "qayta hisoblash tugadi", json.dumps(st)[:160])
        ctx.close()

    ctx, pg = new_page(b, MOB, theme="light")
    pg.goto(BASE + "/baholash")
    pg.wait_for_selector(".ev-kpis .kpi-v")
    pg.wait_for_timeout(2200)
    ow = pg.evaluate("document.querySelector('.scroll').scrollWidth <= document.querySelector('.scroll').clientWidth + 1")
    ok(ow, "mobil 390px: gorizontal toshib chiqish yo'q")
    tall(pg, 390)
    shot(pg, "eval-mobile", full=True)
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.wait_for_timeout(600)
    pg.evaluate("document.querySelector('#savollar').scrollIntoView()")
    pg.wait_for_timeout(400)
    pg.click(".ev-sw .sw")
    pg.wait_for_timeout(400)
    pg.click(".ev-tbl:not(.small) tbody tr >> nth=1")
    pg.wait_for_selector("#sh-drill .drill")
    pg.wait_for_timeout(1000)
    shot(pg, "eval-drill-mobile")
    ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="api,mock,real,reshoot,eval")
    ap.add_argument("--out", default=None, help="skrinshotlar papkasi (standart design/shots/app; s3-* larni buzmaslik uchun /tmp)")
    a = ap.parse_args()
    only = a.only.split(",")
    global OUT
    if a.out:
        OUT = Path(a.out)
    OUT.mkdir(parents=True, exist_ok=True)
    if "api" in only:
        phase_api()
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, fn in (("mock", phase_mock), ("real", phase_real), ("reshoot", phase_reshoot), ("eval", phase_eval)):
            if name in only:
                try:
                    fn(b)
                except Exception as e:  # noqa: BLE001
                    ok(False, f"{name} bosqichi to'xtadi", f"{type(e).__name__}: {str(e)[:300]}")
        b.close()
    passed = sum(r for r, _ in results)
    print(f"\n{passed}/{len(results)} o'tdi · haqiqiy LLM so'rovlari: {llm_calls}")


if __name__ == "__main__":
    main()
