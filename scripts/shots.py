"""Ilova skrinshotlari (Playwright, Chromium). Server ishlab turgan bo'lishi kerak.

    .venv/bin/python scripts/shots.py --base http://127.0.0.1:8000 --out design/shots/app [--only home,chat]

Ssenariylar haqiqiy server bilan ishlaydi (savol -> LLM javobi kutiladi). Faqat "nokey" va "error"
holatlari /api/ask javobini brauzer ichida almashtirib ko'rsatadi (kalitni o'chirib qo'ymaslik uchun).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

DESK = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}
MOB = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
       "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"}


def sse(events: list[tuple[str, dict]]) -> str:
    return "".join(f"event: {e}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for e, d in events)


def fulfill_with(body: str):
    def handler(route):
        route.fulfill(status=200, content_type="text/event-stream", body=body)
    return handler


def ask(page: Page, q: str, timeout=240):
    page.fill(".composer input", q)
    page.keyboard.press("Enter")
    page.wait_for_selector(".turn")
    page.wait_for_function("!document.body.classList.contains('busy')", timeout=timeout * 1000)
    page.wait_for_timeout(1800)  # oqim animatsiyasi tugashi uchun


def fresh(page: Page, base: str, theme="light"):
    page.goto(base + "/")
    page.evaluate(f"localStorage.clear(); localStorage.setItem('dalil.theme', JSON.stringify('{theme}'))")
    page.goto(base + "/")
    page.wait_for_selector(".hero h1")
    page.wait_for_timeout(700)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="design/shots/app")
    ap.add_argument("--only", default="")
    ap.add_argument("--q", default="Prezident qancha muddatga saylanadi?")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, a.only.split(",")))
    want = lambda k: not only or k in only  # noqa: E731
    shot = lambda page, name: (page.screenshot(path=str(out / f"{name}.png")), print("  ", out / f"{name}.png"))  # noqa: E731

    with sync_playwright() as p:
        b = p.chromium.launch()
        for kind, opts in (("desktop", DESK), ("mobile", MOB)):
            for theme in ("light", "dark"):
                if want("home"):
                    ctx = b.new_context(**opts, color_scheme=theme)
                    pg = ctx.new_page()
                    fresh(pg, a.base, theme)
                    shot(pg, f"{kind}-{theme}-1-bosh")
                    ctx.close()
            if want("chat"):
                ctx = b.new_context(**opts)
                pg = ctx.new_page()
                fresh(pg, a.base)
                t0 = time.time()
                pg.click(".sug.tall")
                pg.wait_for_timeout(900)
                shot(pg, f"{kind}-light-2-yuklanmoqda")
                pg.wait_for_function("!document.body.classList.contains('busy')", timeout=240000)
                pg.wait_for_timeout(1800)
                print(f"   javob {time.time() - t0:.0f}s")
                if kind == "mobile":
                    pg.evaluate("document.querySelector('.scroll').scrollTop = 0")
                    pg.wait_for_timeout(300)
                shot(pg, f"{kind}-light-3-javob")
                pg.click(".prose .cite[data-n='2']")
                pg.wait_for_timeout(1200)
                shot(pg, f"{kind}-light-4-iqtibos")
                if kind == "mobile":
                    pg.evaluate("document.querySelector('#sh-sources .card.hl .more').click()")
                    pg.mouse.move(195, 120)
                    pg.wait_for_timeout(200)
                    # varaqni yuqoriga sudrash (large) - orqa sahifa karta bo'lib kichrayadi
                    grab = pg.locator("#sh-sources .grab").bounding_box()
                    x, y = grab["x"] + 60, grab["y"] + 10
                    pg.mouse.move(x, y)
                    pg.mouse.down()
                    pg.mouse.move(x, y - 250, steps=8)
                    pg.mouse.up()
                    pg.wait_for_timeout(900)
                    shot(pg, f"{kind}-light-5-varaq-large")
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(700)
                pg.evaluate("localStorage.setItem('dalil.theme', JSON.stringify('dark'))")
                pg.reload()
                pg.wait_for_timeout(600)
                if kind == "mobile":
                    pg.click(".nav .cbtn")  # tarix
                else:
                    pg.click(".side .hist")
                pg.wait_for_timeout(900)
                shot(pg, f"{kind}-dark-6-tarix")
                ctx.close()
            if want("filters"):
                ctx = b.new_context(**opts)
                pg = ctx.new_page()
                fresh(pg, a.base)
                pg.click(".composer [data-filters]" if kind == "mobile" else ".scopechip")
                pg.wait_for_timeout(500)
                pg.click(("#sh-filters" if kind == "mobile" else "#pop") + " >> text=Barchasi")
                pg.wait_for_timeout(700)
                shot(pg, f"{kind}-light-7-filtrlar")
                ctx.close()
            if want("states"):
                for name, events in (
                    ("8-kalit-yoq", [("sources", {"sources": [], "no_answer": False}),
                                     ("error", {"code": "no_key", "message": "LLM uchun API kalit sozlanmagan. Loyiha papkasidagi .env fayliga GEMINI_API_KEY=... qatorini yozing va serverni qayta ishga tushiring. Manbalar qidiruvi kalitsiz ham ishlaydi."})]),
                    ("9-xato", [("error", {"code": "network", "message": "LLM serveriga ulanib boʻlmadi. Internet aloqasini tekshirib, qayta urinib koʻring."})]),
                ):
                    ctx = b.new_context(**opts)
                    pg = ctx.new_page()
                    fresh(pg, a.base)
                    pg.route("**/api/ask", fulfill_with(sse(events)))
                    ask(pg, "Yillik mehnat taʼtili necha kun?", timeout=20)
                    shot(pg, f"{kind}-light-{name}")
                    ctx.close()
            if want("notfound"):
                ctx = b.new_context(**opts)
                pg = ctx.new_page()
                fresh(pg, a.base)
                ask(pg, "Marsda yer sotib olish uchun qanday litsenziya kerak?")
                shot(pg, f"{kind}-light-10-topilmadi")
                ctx.close()
            if want("cyr"):
                ctx = b.new_context(**opts)
                pg = ctx.new_page()
                fresh(pg, a.base, "dark")
                ask(pg, "Ажралиш учун қандай ҳужжатлар керак?")
                shot(pg, f"{kind}-dark-11-kirillcha")
                ctx.close()
        b.close()


if __name__ == "__main__":
    main()
