"""2-bosqich e2e sinovi va skrinshotlar (Playwright). Sinov serveri ishlab turgan bo'lishi kerak:

    cd web && npx vite build --outDir /tmp/dalil-s2-dist --emptyOutDir && cd ..
    .venv/bin/python scripts/test_server.py --port 8010 --free-limit 30 --dist /tmp/dalil-s2-dist --quota-db /tmp/dalil-s2-quota.sqlite
    .venv/bin/python scripts/stage2_e2e.py [--only api,mock,real,mobile]

Bosqichlar:
  api    - LLM'siz: /api/context (bosqichlar, til, bo'lish, sodda rejim), /api/verify, /api/ask "topilmadi" yo'li
  mock   - LLM'siz, BRAUZERDA SOXTA PROVAYDER (route.fulfill): o'z kaliti yo'li, kirill o'girish, <<<KEYINGI>>> parseri,
           sodda rejim, ulashish menyusi, navigator.share (soxta), Telegram Mini App (soxta Telegram obyekti)
  real   - server kaliti bilan HAQIQIY LLM so'rovlari (har biri hisoblanadi): lotin, sodda, keyingi savol chipi, kirill,
           rus, murakkab, bazada yo'q savol. Desktop skrinshotlar
  reshoot - LLM'siz: real bosqich javoblari (o'zgartirilmagan) localStorage orqali qayta ochiladi, ishonch tekshiruvi
           joriy kod bilan qayta hisoblanadi; desktop skrinshotlar (UI o'zgarganda LLM'ni qayta chaqirmaslik uchun)
  mobile - o'sha suhbatlar mobilda (LLM qayta chaqirilmaydi)
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
from byok_e2e import DESK, MOB, mock_sse, sse_events, tg_script  # noqa: E402

BASE = "http://127.0.0.1:8010"
OUT = ROOT / "design" / "shots" / "app"
CONVS = Path("/tmp/dalil-s2-convs.json")
DEV = "s2-e2e-desk-001"
FAKE_KEY = "AIza-FAKE-dalil-s2"
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "POST, OPTIONS"}

Q_LAT = "Yillik mehnat taʼtili necha kun?"
Q_CYR = "Ажралиш учун қандай ҳужжатлар керак?"
Q_RU = "Сколько дней длится ежегодный трудовой отпуск?"
Q_MIX = "Ishdan boʻshatilganda qanday kompensatsiya toʻlanadi va mehnat daftarchasi qachon beriladi?"
Q_NONE = "Marsda yer sotib olish uchun qanday litsenziya kerak?"

results: list[tuple[bool, str]] = []
llm_calls = 0


def ok(cond, name, info=""):
    results.append((bool(cond), name))
    print(f"{'OK  ' if cond else 'XATO'} {name}" + (f" — {info}" if info else ""), flush=True)
    return cond


def shot(page: Page, name: str):
    p = OUT / f"s2-{name}.png"
    page.screenshot(path=str(p))
    print("     ", p.relative_to(ROOT) if p.is_relative_to(ROOT) else p, flush=True)


def new_page(b, opts, theme="light", ai=None, convs=None, extra="", perms=None):
    ctx = b.new_context(**opts, permissions=perms or [])
    seed = {"dalil.theme": json.dumps(theme), "dalil.did": DEV}
    if ai:
        seed["dalil.ai.v1"] = json.dumps(ai)
    if convs:
        seed["dalil.convs.v1"] = convs
    ctx.add_init_script(f"if (!sessionStorage.getItem('seeded')) {{ const s = {json.dumps(seed)};"
                        "localStorage.clear(); for (const k in s) localStorage.setItem(k, s[k]); sessionStorage.setItem('seeded', 1); }"
                        "window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; };" + extra)
    pg = ctx.new_page()
    pg.route("https://telegram.org/**", lambda r: r.fulfill(status=200, body="", content_type="application/javascript"))
    pg.on("dialog", lambda d: d.accept())
    return ctx, pg


def home(pg: Page):
    pg.goto(BASE + "/")
    pg.wait_for_selector(".hero h1")
    pg.wait_for_timeout(500)


def wait_answer(pg: Page, timeout=200):
    pg.wait_for_timeout(400)
    pg.wait_for_function("!document.body.classList.contains('busy')", timeout=timeout * 1000)
    pg.wait_for_timeout(1200)
    pg.wait_for_function("!document.querySelector('.prose .w, .prose .cite.w')", timeout=60000)
    # ishonch tekshiruvi (serverda) tugashini kutish
    pg.wait_for_function("!document.querySelector('.turn:last-child .trust.tone-wait')", timeout=60000)
    pg.wait_for_timeout(700)


def ask(pg: Page, q: str, timeout=200):
    pg.fill(".composer input", q)
    pg.keyboard.press("Enter")
    wait_answer(pg, timeout)


def last(pg: Page) -> dict:
    return pg.evaluate("""() => { const t = [...document.querySelectorAll('.turn')].pop(); if (!t) return {};
      const q = (s) => t.querySelector(s);
      return { text: q('.prose')?.innerText || '', cites: t.querySelectorAll('.prose .cite').length,
        steps: [...t.querySelectorAll('.steps-list .step')].map(e => e.innerText.replace(/\\n/g, ' ')),
        sum: q('.steps-sum')?.innerText || '', trust: q('.trust')?.innerText || '', notice: q('.notice h4')?.innerText || '',
        msg: q('.notice p')?.innerText || '', fups: [...t.querySelectorAll('.fup')].map(e => e.innerText),
        weak: t.querySelectorAll('.prose .wk').length, seg: !!q('.mode-seg'), explain: !!q('.explain') }; }""")


def to_top_of_last(pg: Page):
    pg.evaluate("(() => { const t = [...document.querySelectorAll('.turn')].pop(); const s = document.querySelector('.scroll');"
                " s.scrollTop = t.offsetTop - 70; })()")
    pg.wait_for_timeout(400)


# ---------------------------------------------------------------- api (LLM'siz)
def phase_api():
    c = httpx.Client(base_url=BASE, timeout=120)
    r = c.post("/api/context", json={"question": Q_LAT}).json()
    keys = [s["key"] for s in r["steps"]]
    ok(keys == ["analyze", "search0", "found", "check"] and all(s["state"] == "done" for s in r["steps"]),
       "/api/context: bosqichlar ro'yxati", " → ".join(f"{s['label']} ({s['detail']})" for s in r["steps"]))
    ok(r["lang"] == "uz" and r["post"] == {"marker": "<<<KEYINGI>>>", "translit": None} and "<<<KEYINGI>>>" in r["prompt"]["system"],
       "lotin savol: lang=uz, prompt oxirida keyingi savollar qoidasi")
    lat_ids = [s["chunk_id"] for s in r["sources"]]

    r = c.post("/api/context", json={"question": Q_CYR}).json()
    ok(r["lang"] == "uz_cyr" and r["post"]["translit"] == "lat2cyr" and "SAVOL: Ajralish uchun qanday hujjatlar kerak?" in r["prompt"]["user"]
       and "LOTIN yozuvida" in r["prompt"]["system"], "kirill savol: lang=uz_cyr, LLM lotinda yozadi, brauzer/server kirillga o'giradi")
    r = c.post("/api/context", json={"question": Q_RU}).json()
    docs = {s["doc_title"] for s in r["sources"][:3]}
    ok(r["lang"] == "ru" and "RUS tilida" in r["prompt"]["system"] and "SAVOL: " + Q_RU in r["prompt"]["user"]
       and any("Mehnat" in d for d in docs), "ruscha savol: lang=ru, ruscha javob ko'rsatmasi, dense Mehnat kodeksini topdi", "; ".join(docs))
    r = c.post("/api/context", json={"question": Q_LAT, "lang": "ru"}).json()
    ok(r["lang"] == "ru", "sozlama: lotin savolga majburan ruscha javob (lang=ru)")

    r = c.post("/api/context", json={"question": Q_MIX}).json()
    keys = [s["key"] for s in r["steps"]]
    found = next(s for s in r["steps"] if s["key"] == "found")
    ids = [s["chunk_id"] for s in r["sources"]]
    ok(len(r["parts"]) == 2 and keys == ["analyze", "search0", "search1", "search2", "found", "check"] and len(ids) == len(set(ids))
       and "takror" in found["detail"], "murakkab savol: 2 qism, 3 qidiruv, RRF, takrorlarsiz",
       f"{r['parts']} | {found['label']}: {found['detail']}")

    r = c.post("/api/context", json={"question": Q_LAT, "mode": "simple", "chunk_ids": lat_ids, "base_answer": "Javob [1]."}).json()
    ok([s["key"] for s in r["steps"]] == ["reuse"] and [s["chunk_id"] for s in r["sources"]] == lat_ids
       and "oddiy odamga" in r["prompt"]["system"] and "YURIDIK JAVOB" in r["prompt"]["user"],
       "sodda rejim: qayta qidiruvsiz, o'sha manbalar o'sha tartibda ([n] o'zgarmaydi)")

    # /api/ask: "topilmadi" (LLM chaqirilmaydi) - step hodisalari oqimda
    t = c.post("/api/ask", json={"question": "qwrtpsdfg zxcvbnm hjklqwe"}, headers={"X-Device-Id": "s2-api-0001"}).text
    ev = sse_events(t)
    names = [e for e, _ in ev]
    ok(names[:2] == ["step", "step"] and "sources" in names and names[-1] == "done" and ev[-1][1]["no_answer"],
       "/api/ask SSE: step... -> sources -> done (topilmadi, LLM'siz)", " ".join(names))

    # /api/verify
    v = c.post("/api/verify", json={"text": "Oʻn sakkiz yoshgacha boʻlgan xodimlarga kamida 45 kalendar kunlik taʼtil beriladi [2].",
                                    "chunk_ids": lat_ids, "lang": "uz"}).json()
    ok(v["level"] in ("low", "medium") and not v["claims"][0]["ok"], "/api/verify: noto'g'ri raqam -> asossiz", json.dumps(v["claims"][0], ensure_ascii=False))


# ---------------------------------------------------------------- mock (soxta provayder, LLM'siz)
LEGAL_MOCK = ("Nikohdan ajratish uchun er-xotinning oʻzaro roziligi boʻlsa, FHDYO organiga birgalikda ariza beriladi [1]. "
              "Voyaga yetmagan bolalar boʻlsa yoki rozilik boʻlmasa, ish sud tartibida koʻriladi [2].\n\n"
              "**<<<KEYINGI>>>**\nAjrim uchun davlat boji qancha?\nAliment qanday belgilanadi?\nSudga ariza qanday yoziladi?")
SIMPLE_MOCK = ("Ikkalangiz rozi boʻlsangiz, FHDYOga birga ariza berasiz [1]. Masalan: Aziz va Malika rozi, bolalari yoʻq — "
               "ular FHDYOda ajrashadi [1]. Bolalar boʻlsa, sudga murojaat qilinadi [2].")


def gemini_route(calls: list, hang=False):
    def h(route):
        req = route.request
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=CORS)
        if hang:
            return  # javob bermaydi: "Javob yozilmoqda" bosqichini ko'rsatish uchun
        body = json.loads(req.post_data or "{}")
        system = body.get("system_instruction", {}).get("parts", [{}])[0].get("text", "")
        calls.append("simple" if "oddiy odamga" in system else "legal")
        text = SIMPLE_MOCK if "oddiy odamga" in system else LEGAL_MOCK
        pieces = [text[i:i + 23] for i in range(0, len(text), 23)]  # ajratgich bo'laklar orasida uziladi
        route.fulfill(status=200, headers={**CORS, "Content-Type": "text/event-stream"},
                      body=mock_sse([json.dumps({"candidates": [{"content": {"parts": [{"text": p}]}}]}) for p in pieces]))
    return h


AI = {"provider": "gemini", "model": "gemini-3.5-flash", "key": FAKE_KEY, "status": "ok"}


def phase_mock(b):
    calls: list[str] = []
    ctx, pg = new_page(b, DESK, ai=AI, perms=["clipboard-read", "clipboard-write"])
    ctxs: list[dict] = []
    pg.on("request", lambda r: ctxs.append(json.loads(r.post_data or "{}")) if r.url.endswith("/api/context") else None)
    pg.route("https://generativelanguage.googleapis.com/**", gemini_route(calls))
    home(pg)
    ask(pg, Q_CYR, timeout=60)
    t = last(pg)
    ok("Никоҳдан ажратиш учун эр-хотиннинг ўзаро розилиги бўлса" in t["text"] and t["cites"] == 2,
       "mock BYOK: lotin javob brauzerda kirillga o'girildi, [n] saqlandi", t["text"][:90])
    ok("KEYINGI" not in t["text"] and "<<<" not in t["text"] and "**" not in t["text"], "mock BYOK: <<<KEYINGI>>> qismi ko'rinmadi")
    ok(t["fups"] == ["Ажрим учун давлат божи қанча?", "Алимент қандай белгиланади?", "Судга ариза қандай ёзилади?"],
       "mock BYOK: 3 ta keyingi savol chipi (kirillda)", str(t["fups"]))
    ok(len(t["steps"]) == 5 and "bosqich" in t["sum"], "mock BYOK: bosqichlar (/api/context steps + yozish) -> yig'ilgan satr", t["sum"])
    ok(t["trust"].startswith("Ishonch:"), "mock BYOK: ishonch belgisi (/api/verify)", t["trust"])
    n_ctx = len(ctxs)
    pg.click(".turn:last-child .explain")
    wait_answer(pg, 60)
    t = last(pg)
    simple_req = ctxs[-1] if len(ctxs) > n_ctx else {}
    ok(simple_req.get("mode") == "simple" and len(simple_req.get("chunk_ids") or []) > 0 and simple_req.get("lang") == "uz_cyr",
       "mock sodda: /api/context mode=simple + chunk_ids (qayta qidiruvsiz), til saqlandi")
    ok(t["seg"] and "Масалан:" in t["text"] and calls == ["legal", "simple"], "mock sodda: sodda javob + Yuridik/Sodda almashtirgich", t["text"][:80])
    pg.click(".turn:last-child .mode-seg button >> nth=0")
    pg.wait_for_timeout(500)
    t2 = last(pg)
    ok("ФҲДЁ органига биргаликда ариза берилади" in t2["text"] and calls == ["legal", "simple"] and len(ctxs) == n_ctx + 1,
       "mock: Yuridik/Sodda almashtirish qayta so'rov yubormaydi")
    # ulashish (desktop menyu)
    pg.click(".turn:last-child .share-wrap .cbtn")
    pg.wait_for_selector(".share-pop.open .sp-thumb img", timeout=5000)
    pg.wait_for_timeout(600)
    ok(pg.is_visible(".share-pop.open >> text=Telegram") and pg.is_visible(".share-pop.open >> text=Rasmni yuklab olish"),
       "desktop ulashish: menyu (Telegram, WhatsApp, nusxalash, rasm)")
    with pg.expect_download() as dl:
        pg.click(".share-pop.open >> text=Rasmni yuklab olish")
    card = OUT / "s2-share-card-kirill-mock.png"
    dl.value.save_as(str(card))
    ok(card.stat().st_size > 50_000, "rasm-kartochka yuklab olindi (mock javob)", str(card.relative_to(ROOT) if card.is_relative_to(ROOT) else card))
    pg.click(".turn:last-child .share-wrap .cbtn")
    pg.wait_for_timeout(400)
    pg.click(".share-pop.open >> text=Telegram")
    pg.click(".turn:last-child .share-wrap .cbtn")
    pg.wait_for_timeout(400)
    pg.click(".share-pop.open >> text=WhatsApp")
    opened = pg.evaluate("window.__opened")
    ok(len(opened) == 2 and opened[0].startswith("https://t.me/share/url?url=") and opened[1].startswith("https://wa.me/?text="),
       "Telegram (t.me/share/url) va WhatsApp (wa.me) havolalari", " | ".join(u[:60] for u in opened))
    pg.click(".turn:last-child .share-wrap .cbtn")
    pg.wait_for_timeout(400)
    pg.click(".share-pop.open >> text=Matnni nusxalash")
    pg.wait_for_timeout(300)
    clip = pg.evaluate("navigator.clipboard.readText()")
    ok(clip.startswith("Savol: " + Q_CYR) and "lex.uz/" in clip and "Dalil — " in clip, "nusxalangan matn: savol + javob + manba havolalari + sayt", clip[-120:].replace("\n", " | "))
    ctx.close()

    # telefon: navigator.share (SOXTA: Playwright Chromium'da tizim ulashish oynasi yo'q)
    share_mock = ("navigator.share = async (d) => { window.__shared = { text: d.text, title: d.title,"
                  " files: (d.files || []).map(f => ({ name: f.name, type: f.type, size: f.size })) }; };"
                  " navigator.canShare = (d) => true;")
    ctx, pg = new_page(b, MOB, ai=AI, extra=share_mock)
    pg.route("https://generativelanguage.googleapis.com/**", gemini_route([]))
    home(pg)
    ask(pg, Q_CYR, timeout=60)
    pg.click(".turn:last-child .share-wrap .cbtn")
    pg.wait_for_timeout(1500)
    sh = pg.evaluate("window.__shared")
    ok(sh and sh["files"] and sh["files"][0]["type"] == "image/png" and sh["files"][0]["size"] > 50_000 and "Savol:" in sh["text"],
       "telefon: navigator.share (mock) - matn + PNG fayl (Web Share Level 2)", json.dumps(sh["files"] if sh else None))
    ok(not pg.is_visible(".share-pop.open"), "telefon: tizim oynasi ishlaganda menyu ochilmadi")
    ctx.close()

    # "Javob yozilmoqda" bosqichi (provayder javob bermaydi) - mobil skrinshot uchun
    ctx, pg = new_page(b, MOB, ai=AI)
    pg.route("https://generativelanguage.googleapis.com/**", gemini_route([], hang=True))
    home(pg)
    pg.fill(".composer input", Q_LAT)
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".step.run >> text=Javob yozilmoqda", timeout=30000)
    pg.wait_for_timeout(900)
    ok(pg.locator(".steps-list .step").count() == 5, "mobil: bosqichlar bittadan ochiladi, oxirgisi 'Javob yozilmoqda'")
    shot(pg, "mobile-1-bosqichlar-mock")
    pg.unroute_all(behavior="ignoreErrors")
    ctx.close()


# ---------------------------------------------------------------- real (haqiqiy LLM)
def phase_real(b):
    global llm_calls
    q0 = httpx.get(BASE + "/api/quota", headers={"X-Device-Id": DEV}).json()
    ctx, pg = new_page(b, DESK, perms=["clipboard-read", "clipboard-write"])
    home(pg)

    # 1. lotin
    llm_calls += 1
    pg.fill(".composer input", Q_LAT)
    pg.keyboard.press("Enter")
    try:
        pg.wait_for_selector(".step.run >> text=Javob yozilmoqda", timeout=30000)
        pg.wait_for_timeout(700)
        shot(pg, "desktop-1-bosqichlar")
    except Exception:  # noqa: BLE001
        ok(False, "desktop: 'Javob yozilmoqda' bosqichi ko'rindi")
    wait_answer(pg)
    t = last(pg)
    ok(t["cites"] > 0 and not t["notice"] and len(t["fups"]) >= 2 and "KEYINGI" not in t["text"],
       "haqiqiy lotin: javob + [n] + keyingi savollar (ajratgich ko'rinmaydi)", f"{t['sum']} | {t['trust']} | {t['fups']}")
    ok(t["trust"].startswith("Ishonch:"), "haqiqiy lotin: ishonch belgisi", f"{t['trust']}, belgilangan so'zlar: {t['weak']}")
    to_top_of_last(pg)
    shot(pg, "desktop-2-javob")
    if pg.locator(".turn:last-child button.trust").count():
        pg.click(".turn:last-child button.trust")
        pg.wait_for_timeout(700)
        shot(pg, "desktop-3-ishonch")
        pg.click(".turn:last-child button.trust")
    # bosqichlarni ochish
    pg.click(".turn:last-child .steps-sum")
    pg.wait_for_timeout(700)
    to_top_of_last(pg)
    shot(pg, "desktop-2b-bosqichlar-ochiq")
    pg.click(".turn:last-child .steps-sum")

    # 2. sodda
    llm_calls += 1
    pg.click(".turn:last-child .explain")
    wait_answer(pg)
    t = last(pg)
    ok(t["seg"] and t["cites"] > 0 and not t["notice"], "haqiqiy sodda: qayta qidiruvsiz sodda javob, [n] saqlandi", t["text"][:140].replace("\n", " "))
    to_top_of_last(pg)
    shot(pg, "desktop-4-sodda")
    pg.click(".turn:last-child .mode-seg button >> nth=0")
    pg.wait_for_timeout(500)

    # ulashish menyusi + rasm-kartochka (haqiqiy javob)
    pg.evaluate("document.querySelector('.scroll').scrollTop = 1e6")
    pg.wait_for_timeout(300)
    pg.click(".turn:last-child .share-wrap .cbtn")
    pg.wait_for_selector(".share-pop.open .sp-thumb img", timeout=5000)
    pg.wait_for_timeout(700)
    shot(pg, "desktop-5-ulashish")
    with pg.expect_download() as dl:
        pg.click(".share-pop.open >> text=Rasmni yuklab olish")
    dl.value.save_as(str(OUT / "s2-share-card.png"))
    ok((OUT / "s2-share-card.png").stat().st_size > 50_000, "rasm-kartochka (haqiqiy javob) saqlandi", "design/shots/app/s2-share-card.png")

    # 3. keyingi savol chipi
    fups = last(pg)["fups"]
    if ok(fups, "keyingi savol chiplari bor"):
        llm_calls += 1
        n_turns = pg.locator(".turn").count()
        pg.click(".turn:last-child .fup >> nth=0")
        wait_answer(pg)
        t = last(pg)
        ok(pg.locator(".turn").count() == n_turns + 1 and t["cites"] > 0, "chip bosildi: shu suhbatda yangi savol va javob",
           f"{fups[0]} -> {t['text'][:80]}")

    # 4. murakkab savol (yangi suhbat)
    pg.click(".side .newchat")
    pg.wait_for_timeout(800)
    llm_calls += 1
    ask(pg, Q_MIX)
    t = last(pg)
    pg.click(".turn:last-child .steps-sum")
    pg.wait_for_timeout(700)
    t = last(pg)
    ok(any("Qidirilmoqda: «" in s for s in t["steps"]) and t["cites"] > 0, "haqiqiy murakkab: 2 qism alohida qidirildi, javob",
       " / ".join(t["steps"]))
    to_top_of_last(pg)
    shot(pg, "desktop-6-murakkab")

    # 5. ruscha
    pg.click(".side .newchat")
    pg.wait_for_timeout(800)
    llm_calls += 1
    ask(pg, Q_RU)
    t = last(pg)
    cyr = sum(1 for ch in t["text"] if "а" <= ch.lower() <= "я")
    ok(cyr > len(t["text"]) * 0.4 and t["cites"] > 0, "haqiqiy rus: javob ruscha, [n] bor", t["text"][:120].replace("\n", " "))
    src = pg.inner_text(".inspector .card h3")
    ok("modda" in src, "rus: manba kartochkalari asl o'zbekcha", src)
    to_top_of_last(pg)
    shot(pg, "desktop-8-ruscha")

    # 6. bazada yo'q
    pg.click(".side .newchat")
    pg.wait_for_timeout(800)
    ask(pg, Q_NONE)
    t = last(pg)
    used = httpx.get(BASE + "/api/quota", headers={"X-Device-Id": DEV}).json()["used"] - q0["used"]
    if used > llm_calls:
        llm_calls += 1
    ok(t["notice"] == "Bazada mos modda topilmadi", "bazada yo'q savol: 'topilmadi', taxmin qilinmadi", t["msg"][:80])
    shot(pg, "desktop-9-topilmadi")

    # 7. kirill (qorong'i)
    pg.evaluate("localStorage.setItem('dalil.theme', JSON.stringify('dark'))")
    pg.reload()
    pg.wait_for_selector(".hero h1")
    pg.wait_for_timeout(600)
    llm_calls += 1
    ask(pg, Q_CYR)
    t = last(pg)
    lat = sum(1 for ch in t["text"] if "a" <= ch.lower() <= "z")
    ok(lat < 15 and any(ch in t["text"] for ch in "ўқғҳ") and t["cites"] > 0, "haqiqiy kirill: javob o'zbek kirillda, [n] saqlandi",
       t["text"][:120].replace("\n", " "))
    ok(all(any(ch in f for ch in "абвгдеёжзийклмнопрстуфхўқғҳ") for f in t["fups"]), "kirill: keyingi savollar ham kirillda", str(t["fups"]))
    to_top_of_last(pg)
    shot(pg, "desktop-dark-7-kirill")
    # til sozlamasi (filtr popover)
    pg.evaluate("localStorage.setItem('dalil.theme', JSON.stringify('light'))")
    pg.reload()
    pg.wait_for_selector(".hero h1")
    pg.wait_for_timeout(500)
    pg.click(".side .hist >> nth=0")
    pg.wait_for_timeout(800)
    pg.click(".scopechip")
    pg.wait_for_timeout(700)
    shot(pg, "desktop-10-til-sozlamasi")
    pg.keyboard.press("Escape")
    used = httpx.get(BASE + "/api/quota", headers={"X-Device-Id": DEV}).json()["used"] - q0["used"]
    ok(used == llm_calls, "server kaliti bilan LLM so'rovlari soni kvota hisoblagichi bilan mos", f"kvota: {used}, skript: {llm_calls}")
    llm_calls = used
    CONVS.write_text(pg.evaluate("localStorage.getItem('dalil.convs.v1')"))
    ctx.close()


# ---------------------------------------------------------------- reshoot (LLM'siz)
def reverified() -> str:
    """real bosqichdagi suhbatlar: javob matnlari o'zgarmaydi, ishonch tekshiruvi (/api/verify, LLM'siz) va keyingi
    savollar parseri joriy kod bilan qayta qo'llanadi."""
    sys.path.insert(0, str(ROOT))
    from lexrag.lang import parse_followups
    convs = json.loads(CONVS.read_text())
    c = httpx.Client(base_url=BASE, timeout=120)
    for conv in convs:
        for t in conv["turns"]:
            ids = [s["chunk_id"] for s in t["sources"]]
            for mode, v in (("legal", t), ("simple", t.get("simple"))):
                if not v:
                    continue
                if v.get("followups"):
                    v["followups"] = parse_followups("\n".join(v["followups"]))
                if v.get("status") == "done" and v.get("text") and ids:
                    v["trust"] = c.post("/api/verify", json={"text": v["text"], "chunk_ids": ids, "lang": t.get("lang") or "uz",
                                                             "mode": mode}).json()
    return json.dumps(convs, ensure_ascii=False)


def phase_reshoot(b):
    """Desktop skrinshotlar saqlangan haqiqiy javoblardan (real bosqich LLM'ni qayta chaqirmasdan)."""
    if not CONVS.exists():
        ok(False, "reshoot: real bosqich suhbatlari bor")
        return
    convs = reverified()
    Path("/tmp/dalil-s2-convs-v2.json").write_text(convs)
    levels = [(t["q"][:30], m, (v.get("trust") or {}).get("level")) for cv in json.loads(convs) for t in cv["turns"]
              for m, v in (("legal", t), ("simple", t.get("simple"))) if v and isinstance(v.get("trust"), dict)]
    print("      ishonch:", levels, flush=True)

    def open_desk(pg, part):
        pg.click(f".side .hist:has-text('{part}')")
        pg.wait_for_timeout(900)

    ctx, pg = new_page(b, DESK, convs=convs)
    home(pg)
    open_desk(pg, "Yillik mehnat")
    first = "(() => { const t = document.querySelectorAll('.turn')[0]; document.querySelector('.scroll').scrollTop = t.offsetTop - 70; })()"
    pg.evaluate(first)
    pg.wait_for_timeout(400)
    shot(pg, "desktop-2-javob")
    pg.click(".turn >> nth=0 >> button.trust")
    pg.wait_for_timeout(700)
    shot(pg, "desktop-3-ishonch")
    pg.click(".turn >> nth=0 >> button.trust")
    pg.click(".turn >> nth=0 >> .mode-seg button >> nth=1")
    pg.wait_for_timeout(700)
    pg.evaluate(first)
    pg.wait_for_timeout(300)
    t = pg.evaluate("document.querySelectorAll('.turn')[0].querySelectorAll('.prose .cite').length")
    raw = pg.evaluate("/\\[\\d+,/.test(document.querySelectorAll('.turn')[0].querySelector('.prose').innerText)")
    ok(t > 0 and not raw, "sodda javob: '[2, 7]' ham iqtibos tugmasi bo'ldi", f"{t} ta tugma")
    shot(pg, "desktop-4-sodda")
    pg.click(".turn >> nth=0 >> .mode-seg button >> nth=0")
    pg.wait_for_timeout(500)
    pg.evaluate("(() => { const t = document.querySelectorAll('.turn')[0]; document.querySelector('.scroll').scrollTop = t.offsetTop + t.offsetHeight - 560; })()")
    pg.wait_for_timeout(300)
    pg.click(".turn >> nth=0 >> .share-wrap .cbtn")
    pg.wait_for_selector(".share-pop.open .sp-thumb img", timeout=5000)
    pg.wait_for_timeout(700)
    shot(pg, "desktop-5-ulashish")
    with pg.expect_download() as dl:
        pg.click(".share-pop.open >> text=Rasmni yuklab olish")
    dl.value.save_as(str(OUT / "s2-share-card.png"))
    ok((OUT / "s2-share-card.png").stat().st_size > 50_000, "rasm-kartochka (haqiqiy javob) saqlandi", "design/shots/app/s2-share-card.png")
    open_desk(pg, "Ishdan bo")
    pg.click(".turn:last-child .steps-sum")
    pg.wait_for_timeout(800)
    to_top_of_last(pg)
    shot(pg, "desktop-6-murakkab")
    open_desk(pg, "Сколько")
    to_top_of_last(pg)
    shot(pg, "desktop-8-ruscha")
    open_desk(pg, "Marsda")
    shot(pg, "desktop-9-topilmadi")
    pg.click(".scopechip")
    pg.wait_for_timeout(700)
    shot(pg, "desktop-10-til-sozlamasi")
    ctx.close()

    ctx, pg = new_page(b, DESK, theme="dark", convs=convs)
    home(pg)
    open_desk(pg, "Ажралиш")
    to_top_of_last(pg)
    shot(pg, "desktop-dark-7-kirill")
    ctx.close()


# ---------------------------------------------------------------- mobile (LLM'siz, suhbatlar ko'chiriladi)
def open_conv(pg: Page, title_part: str):
    pg.click(".nav .cbtn")
    pg.wait_for_timeout(700)
    pg.click(f"#sh-history .hlist .row:has-text('{title_part}')")
    pg.wait_for_timeout(900)


def phase_mobile(b):
    if not CONVS.exists():
        ok(False, "mobil: real bosqich suhbatlari bor (avval --only real)")
        return
    v2 = Path("/tmp/dalil-s2-convs-v2.json")
    convs = v2.read_text() if v2.exists() else CONVS.read_text()
    ctx, pg = new_page(b, MOB, convs=convs)
    home(pg)
    open_conv(pg, "Yillik mehnat")
    pg.evaluate("(() => { const t = document.querySelectorAll('.turn')[0]; document.querySelector('.scroll').scrollTop = t.offsetTop - 70; })()")
    pg.wait_for_timeout(500)
    shot(pg, "mobile-2-javob")
    pg.evaluate("(() => { const t = document.querySelectorAll('.turn')[0]; document.querySelector('.scroll').scrollTop = t.offsetTop + t.offsetHeight - 700; })()")
    pg.wait_for_timeout(400)
    shot(pg, "mobile-2b-javob-pasti")
    # sodda ko'rinish (birinchi savol) - so'rovsiz almashadi
    pg.click(".turn >> nth=0 >> .mode-seg button >> nth=1")
    pg.wait_for_timeout(600)
    pg.evaluate("(() => { const t = document.querySelectorAll('.turn')[0]; document.querySelector('.scroll').scrollTop = t.offsetTop - 70; })()")
    pg.wait_for_timeout(400)
    shot(pg, "mobile-3-sodda")
    pg.click(".composer [data-filters]")
    pg.wait_for_timeout(700)
    pg.evaluate("document.querySelector('#sh-filters .sh-body').scrollTop = 1e6")
    pg.wait_for_timeout(400)
    shot(pg, "mobile-6-til")
    ctx.close()

    ctx, pg = new_page(b, MOB, theme="dark", convs=convs)
    home(pg)
    open_conv(pg, "Ажралиш")
    pg.evaluate("document.querySelector('.scroll').scrollTop = 0")
    pg.wait_for_timeout(400)
    shot(pg, "mobile-dark-4-kirill")
    ctx.close()

    # Telegram Mini App (SOXTA Telegram obyekti): ulashish menyusi, Telegram -> openTelegramLink
    tg = tg_script("query_id=AAE2e&user=%7B%22id%22%3A42%7D&auth_date=1&hash=x", {}) + \
        "window.Telegram.WebApp.openTelegramLink = (u) => { window.__tgLink = u; }; window.Telegram.WebApp.openLink = (u) => { window.__tgOpen = u; };"
    ctx, pg = new_page(b, MOB, convs=convs, extra=tg)
    home(pg)
    open_conv(pg, "Yillik mehnat")
    pg.evaluate("(() => { const t = document.querySelectorAll('.turn')[0]; document.querySelector('.scroll').scrollTop = t.offsetTop + t.offsetHeight - 620; })()")
    pg.wait_for_timeout(400)
    pg.click(".turn >> nth=0 >> .share-wrap .cbtn")
    pg.wait_for_selector(".share-pop.open .sp-thumb img", timeout=5000)
    pg.wait_for_timeout(600)
    shot(pg, "mobile-5-ulashish-telegram-mock")
    pg.click(".share-pop.open >> text=Telegram")
    link = pg.evaluate("window.__tgLink || ''")
    ok(link.startswith("https://t.me/share/url?url="), "Telegram Mini App (mock): Telegram.WebApp.openTelegramLink chaqirildi", link[:70])
    ctx.close()


def main():
    global llm_calls
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="api,mock,real,reshoot,mobile")
    ap.add_argument("--out", default=None, help="skrinshotlar papkasi (s2-* larni buzmaslik uchun /tmp)")
    a = ap.parse_args()
    only = a.only.split(",")
    global OUT
    if a.out:
        OUT = Path(a.out)
    OUT.mkdir(parents=True, exist_ok=True)
    if not httpx.get(BASE + "/api/health", timeout=5).json().get("index_ready"):
        raise SystemExit("Sinov serveri tayyor emas")
    if "api" in only:
        print("\n--- api", flush=True)
        phase_api()
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, fn in (("mock", phase_mock), ("real", phase_real), ("reshoot", phase_reshoot), ("mobile", phase_mobile)):
            if name in only:
                print(f"\n--- {name}", flush=True)
                try:
                    fn(b)
                except Exception as e:  # noqa: BLE001
                    ok(False, f"{name} bosqichi yiqildi", f"{type(e).__name__}: {str(e)[:400]}")
        b.close()
    bad = [n for c, n in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} o'tdi; server kaliti bilan haqiqiy LLM so'rovlari: {llm_calls}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
