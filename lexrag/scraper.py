"""lex.uz scraper.

1) `scrape_list()`  - "Qonunlar" ro'yxatining barcha sahifalarini (ASP.NET postback) aylanib,
   data/state/list_index.jsonl ga yozadi. Har sahifa HTML'i data/raw/list/ da saqlanadi,
   to'xtab qolsa oxirgi saqlangan sahifadan davom etadi.
2) `fetch_docs()`   - har hujjat uchun matn sahifasi (/uz/docs/<id>) va rekvizitlar
   kartochkasini (/uz/actinfo/card1/<id>) yuklaydi. Raw fayl bor bo'lsa qayta yuklamaydi.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from tqdm import tqdm

from . import config
from .http import PoliteClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- yordamchi
def atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def log_failure(stage: str, lex_id: str, error: str):
    with open(config.FAILURES, "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage, "lex_id": lex_id, "error": error[:500],
                            "ts": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")


def load_list_index() -> list[dict]:
    if not config.LIST_INDEX.exists():
        return []
    with open(config.LIST_INDEX, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def raw_doc_path(lex_id: str) -> Path:
    return config.RAW_DOCS / f"{lex_id}.html"


def raw_card_path(lex_id: str) -> Path:
    return config.RAW_CARDS / f"{lex_id}.html"


# ---------------------------------------------------------------- ro'yxat
def _form_fields(soup: BeautifulSoup) -> dict:
    form = soup.find("form", id="Form1")
    data = {}
    for i in form.select("input[name]"):
        t = (i.get("type") or "").lower()
        if t in ("checkbox", "radio") and not i.has_attr("checked"):
            continue
        if t in ("submit", "button", "image"):
            continue
        data[i["name"]] = i.get("value", "")
    for sel in form.select("select[name]"):
        opt = sel.select_one("option[selected]") or sel.select_one("option")
        data[sel["name"]] = opt.get("value", "") if opt else ""
    return data


STATUS_MAP = {"status_code_y": "amalda", "status_code_r": "kuchini yo'qotgan",
              "status_code_n": "amalda emas"}


def parse_list_page(html: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "lxml")
    total = None
    m = re.search(r"(\d[\d\s]*)\s+hujjat topildi", soup.get_text(" "))
    if m:
        total = int(re.sub(r"\s", "", m.group(1)))
    rows = []
    for tr in soup.select("tr.dd-table__main-item"):
        a = tr.select_one(".dd-table__main-left-desc a")
        if not a:
            continue
        href = a["href"]
        lex_id = re.search(r"/docs/(-?\d+)", href).group(1)
        icon = tr.select_one(".lx_act_state i")
        st_cls = next((c for c in (icon.get("class") or []) if c.startswith("status_code")), None) if icon else None
        badge = tr.select_one(".dd-table__main-extra .badge")
        rows.append({
            "pos": int(tr.select_one(".dd-table__main-item_number").get_text(strip=True)),
            "lex_id": lex_id,
            "title": a.get_text(" ", strip=True),
            "requisites": badge.get_text(" ", strip=True) if badge else "",
            "list_status": STATUS_MAP.get(st_cls, st_cls),
            "url": config.BASE + href,
        })
    return rows, total


def scrape_list(client: PoliteClient | None = None, max_pages: int | None = None) -> list[dict]:
    client = client or PoliteClient()
    for name, spec in config.COLLECTIONS.items():
        _scrape_collection(client, name, spec, max_pages)
    return rebuild_list_index()


def _scrape_collection(client: PoliteClient, name: str, spec: dict, max_pages: int | None = None):
    url = spec["url"]
    pdir = config.RAW_LIST / name
    pdir.mkdir(parents=True, exist_ok=True)
    pages = sorted(pdir.glob("page_*.html"))
    if pages:
        last = pages[-1]
        page_no = int(last.stem.split("_")[1])
        html = last.read_text(encoding="utf-8")
        log.info("%s ro'yxati: %d-sahifadan davom etaman", name, page_no)
    else:
        page_no = 1
        html = client.get(url).text
        atomic_write(pdir / "page_001.html", html)

    rows, total = parse_list_page(html)
    total = total or spec["expected"]
    n_pages = -(-total // config.PAGE_SIZE)
    if max_pages:
        n_pages = min(n_pages, max_pages)
    bar = tqdm(total=n_pages, initial=page_no, desc=f"{name} ro'yxati")
    while page_no < n_pages and len(rows) == config.PAGE_SIZE:
        soup = BeautifulSoup(html, "lxml")
        data = _form_fields(soup)
        data["__EVENTTARGET"] = "ucFoundActsControl$LinkButton1"  # "Keyingisi"
        data["__EVENTARGUMENT"] = ""
        html = client.post(url, data=data).text
        page_no += 1
        rows, _ = parse_list_page(html)
        expected_first = (page_no - 1) * config.PAGE_SIZE + 1
        if not rows or rows[0]["pos"] != expected_first:
            raise RuntimeError(f"{page_no}-sahifa kutilgandek emas (birinchi pos={rows[0]['pos'] if rows else None})")
        atomic_write(pdir / f"page_{page_no:03d}.html", html)
        bar.update(1)
    bar.close()


def rebuild_list_index() -> list[dict]:
    """Saqlangan sahifalardan list_index.jsonl ni qayta yig'adi (dublikatlarsiz)."""
    seen, out = set(), []
    for name in config.COLLECTIONS:
        for p in sorted((config.RAW_LIST / name).glob("page_*.html")):
            rows, total = parse_list_page(p.read_text(encoding="utf-8"))
            for r in rows:
                if r["lex_id"] in seen:
                    continue
                seen.add(r["lex_id"])
                r["collection"] = name
                out.append(r)
    with open(config.LIST_INDEX, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.info("list_index: %d ta hujjat", len(out))
    return out


# ---------------------------------------------------------------- hujjatlar
def _valid_doc_html(html: str) -> bool:
    return 'id="divCont"' in html and "lx_elem" in html


def fetch_one(client: PoliteClient, lex_id: str) -> bool:
    ok = True
    dp = raw_doc_path(lex_id)
    if not dp.exists():
        try:
            html = client.get(config.DOC_URL.format(lex_id=lex_id)).text
            if not _valid_doc_html(html):
                raise ValueError("sahifada hujjat matni (divCont) topilmadi")
            atomic_write(dp, html)
        except Exception as e:  # noqa: BLE001
            log_failure("fetch_doc", lex_id, repr(e))
            ok = False
    cp = raw_card_path(lex_id)
    if not cp.exists():
        try:
            html = client.get(config.CARD_URL.format(lex_id=lex_id)).text
            atomic_write(cp, html)
        except Exception as e:  # noqa: BLE001
            log_failure("fetch_card", lex_id, repr(e))  # kartochka bo'lmasa ham davom etamiz
    return ok


def select_sample(rows: list[dict], n: int) -> list[dict]:
    """Ro'yxat bo'ylab teng taqsimlangan n ta hujjat (yangi va eski qonunlar aralash)."""
    if n >= len(rows):
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def fetch_docs(rows: list[dict], client: PoliteClient | None = None) -> dict:
    client = client or PoliteClient()
    todo = [r for r in rows if not (raw_doc_path(r["lex_id"]).exists() and raw_card_path(r["lex_id"]).exists())]
    log.info("Jami %d, yuklanadigan %d (qolganlari raw/ da bor)", len(rows), len(todo))
    ok = fail = 0
    t0 = time.time()
    for r in tqdm(todo, desc="hujjatlar"):
        if fetch_one(client, r["lex_id"]):
            ok += 1
        else:
            fail += 1
    return {"total": len(rows), "fetched_now": ok, "failed_now": fail, "seconds": round(time.time() - t0)}
