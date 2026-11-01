"""4-bosqich e2e (LLM'siz): kirill so'z tiklash va ruscha savol X-ray'da, ruscha ishonch tekshiruvi, /baholash
"Oldin / keyin" bloki va Dev/Test almashtirgich + skrinshotlar (design/shots/app/s4-*.png). Sinov serveri kerak:

    cd web && npx vite build --outDir /tmp/dalil-s4-dist --emptyOutDir && cd ..
    .venv/bin/python scripts/test_server.py --port 8010 --free-limit 30 --dist /tmp/dalil-s4-dist \
        --quota-db /tmp/dalil-s4-quota.sqlite
    .venv/bin/python scripts/stage4_e2e.py [--only api,eval]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from byok_e2e import DESK, MOB  # noqa: E402
from stage2_e2e import new_page  # noqa: E402

BASE = "http://127.0.0.1:8010"
OUT = ROOT / "design" / "shots" / "app"
Q_CYR_KB = "Пенсионер касалхонада ётиб даволанса, пенсияси тулик туланадими?"   # rus klaviaturasida
Q_RU = "Сколько дней длится ежегодный трудовой отпуск?"

results: list[tuple[bool, str]] = []


def ok(cond, name, info=""):
    results.append((bool(cond), name))
    print(f"{'OK  ' if cond else 'XATO'} {name}" + (f" — {info}" if info else ""), flush=True)
    return cond


def shot(target, name: str, full: bool = False):
    p = OUT / f"s4-{name}.png"
    if isinstance(target, Page):
        target.screenshot(path=str(p), full_page=full)
    else:
        target.screenshot(path=str(p))
    print("     ", p.relative_to(ROOT), flush=True)


def block_shot(pg: Page, name: str, width: int, height: int):
    """Ilova ichki scroll'li: blok to'liq tushishi uchun oyna vaqtincha balandlatiladi."""
    h = pg.evaluate("document.querySelector('.scroll').scrollHeight")
    pg.set_viewport_size({"width": width, "height": int(h) + 10})
    pg.wait_for_timeout(900)
    pg.mouse.move(2, 2)
    shot(pg.locator("#oldin-keyin"), name)
    pg.set_viewport_size({"width": width, "height": height})
    pg.wait_for_timeout(500)


def pct(v: float) -> str:
    return f"{v * 100:.1f}".replace(".", ",") + "%"


# ---------------------------------------------------------------- api
def phase_api():
    c = httpx.Client(base_url=BASE, timeout=120)
    x = c.post("/api/context", json={"question": Q_CYR_KB, "xray": True}).json()["xray"]["searches"][0]
    ok("tulik" in x["q_dense"] and "toʻliq" in x["q_bm25"],
       "kirill (rus klaviaturasi): dense lotinlashtirilgan matn, BM25 tiklangan soʻzlar",
       f"dense: {x['q_dense'][:70]} | bm25: {x['q_bm25'][:70]}")
    ok(x["params"]["tokenizer"]["kind"] == "stem" and "toliq" in x["bm25_tokens"], "BM25: stemmer tokenlari X-ray'da",
       " ".join(x["bm25_tokens"]))
    r = c.post("/api/context", json={"question": Q_RU, "xray": True}).json()["xray"]["searches"][0]
    ok(r["q_bm25"] == "" and not r["bm25"], "ruscha savol BM25'ga yuborilmaydi")
    a = json.loads((ROOT / "eval" / "answers_ru.json").read_text(encoding="utf-8"))["items"]
    lv = [c.post("/api/verify", json={"text": i["answer"], "chunk_ids": i["chunk_ids"], "lang": "ru"}).json()["level"]
          for i in a if i["status"] == "ok"]
    ok("low" not in lv, "/api/verify: haqiqiy ruscha javoblarda 'Past' yoʻq", str(lv))
    e = c.get("/api/eval").json()
    bs = e["results"].get("by_split") or {}
    ok(set(bs) == {"dev", "test"} and e.get("baseline_v2") and e.get("trust_cal"),
       "/api/eval: by_split, baseline_v2, trust_cal", f"TEST {bs.get('test', {}).get('n_questions')} / DEV {bs.get('dev', {}).get('n_questions')}")
    return e


# ---------------------------------------------------------------- /baholash
def open_eval(b, size, theme):
    ctx, pg = new_page(b, size, theme=theme)
    pg.goto(BASE + "/baholash", wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_selector(".ev-kpis .kpi-v", timeout=90000)
    pg.wait_for_selector("#oldin-keyin .ba-row")
    pg.wait_for_timeout(1800)
    pg.mouse.move(2, 2)
    return ctx, pg


def tall(pg: Page, width: int):
    h = pg.evaluate("document.querySelector('.scroll').scrollHeight")
    pg.set_viewport_size({"width": width, "height": int(h) + 10})
    pg.wait_for_timeout(1400)


def phase_eval(b, e):
    bs = e["results"]["by_split"]
    for theme in ("light", "dark"):
        ctx, pg = open_eval(b, DESK, theme)
        if theme == "light":
            kpi = pg.inner_text(".ev-kpis .kpi-v >> nth=0")
            ok(kpi == pct(bs["test"]["summary"]["hybrid"]["recall@5"]), "standart: TEST qismi (KPI recall@5)", kpi)
            n = pg.locator("#oldin-keyin .ba-row").count()
            ok(n == 9, "Oldin / keyin: 9 qator (gibrid, BM25, kirill, lotin, rus)", str(n))
            txt = pg.inner_text("#oldin-keyin")
            row = pg.inner_text("#oldin-keyin .ba-row >> nth=3")
            got = [float(x.replace(",", ".")) for x in re.findall(r"(\d+,\d)%", row)[:2]]
            want = [e["baseline_v2"]["by_split"]["test"]["summary"]["bm25"]["recall@5"] * 100, bs["test"]["summary"]["bm25"]["recall@5"] * 100]
            # JS toFixed va Python format yarimni turlicha yaxlitlaydi (31.25 -> 31,3 / 31.2): 0.1 farqqacha
            ok(len(got) == 2 and all(abs(g - w) <= 0.051 for g, w in zip(got, want)),
               "Oldin / keyin: BM25 R@5 qiymatlari baseline_v2 va results bilan bir xil", f"{got} ~ {[round(w, 2) for w in want]}")
            ok("Yuqori" in txt and "Past" in txt, "Oldin / keyin: ruscha ishonch darajalari")
            ok(f"{bs['test']['n_questions']} savol" in pg.inner_text(".ev-split"), "almashtirgich izohi: TEST hajmi")
            block_shot(pg, "before-after-desktop", 1440, 900)
            pg.click(".ev-split .ev-seg button >> nth=1")
            pg.wait_for_timeout(900)
            kpi = pg.inner_text(".ev-kpis .kpi-v >> nth=0")
            ok(kpi == pct(bs["dev"]["summary"]["hybrid"]["recall@5"]), "Dev'ga oʻtish: KPI DEV qiymati", kpi)
            rows = pg.locator(".ev-tbl:not(.small) tbody tr").count()
            ok(rows == bs["dev"]["n_questions"], "Dev: savollar jadvali faqat DEV", f"{rows} qator")
            pg.mouse.move(2, 2)
            pg.wait_for_timeout(500)
            block_shot(pg, "before-after-dev-desktop", 1440, 900)
            pg.click(".ev-split .ev-seg button >> nth=0")
            pg.wait_for_timeout(700)
            pg.evaluate("document.querySelector('.scroll').scrollTo({top: 0})")
            pg.mouse.move(2, 2)
            pg.wait_for_timeout(400)
            shot(pg, "eval-desktop-top")
        else:
            block_shot(pg, "before-after-desktop-dark", 1440, 900)
        tall(pg, 1440)
        shot(pg, f"eval-desktop{'-dark' if theme == 'dark' else ''}", full=True)
        ctx.close()
    for theme in ("light", "dark"):
        ctx, pg = open_eval(b, MOB, theme)
        if theme == "light":
            ow = pg.evaluate("document.querySelector('.scroll').scrollWidth <= document.querySelector('.scroll').clientWidth + 1")
            ok(ow, "mobil 390px: gorizontal toshib chiqish yoʻq")
            seg_w = pg.evaluate("document.querySelector('.ev-split .ev-seg').getBoundingClientRect().width")
            ok(seg_w > 200, "mobil: almashtirgich koʻrinadi", f"{seg_w:.0f}px")
        pg.evaluate("document.querySelector('#oldin-keyin').scrollIntoView({block: 'start'})")
        pg.wait_for_timeout(500)
        block_shot(pg, "before-after-mobile" + ("-dark" if theme == "dark" else ""), 390, 844)
        if theme == "light":
            pg.evaluate("document.querySelector('.scroll').scrollTo({top: 0})")
            pg.wait_for_timeout(400)
            shot(pg, "eval-mobile-top")
            tall(pg, 390)
            shot(pg, "eval-mobile", full=True)
        ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="api,eval")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    e = phase_api() if "api" in a.only else httpx.get(BASE + "/api/eval", timeout=30).json()
    if "eval" in a.only:
        with sync_playwright() as p:
            b = p.chromium.launch()
            try:
                phase_eval(b, e)
            except Exception as ex:  # noqa: BLE001
                ok(False, "eval bosqichi", f"{type(ex).__name__}: {ex}")
            b.close()
    bad = [n for c, n in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} o'tdi")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
