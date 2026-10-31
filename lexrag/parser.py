"""Raw HTML -> tozalangan hujjat (data/clean/<id>.json) va metadata.csv.

lex.uz hujjat sahifasida matn `#divCont` ichida, har element alohida `div` bo'lib keladi.
Elementning birinchi CSS klassi uning rolini bildiradi:
  ACT_FORM / ACT_TITLE         - hujjat shakli va nomi
  GRIF_PARLAMENT               - "Qonunchilik palatasi tomonidan ... qabul qilingan"
  TEXT_HEADER_DEFAULT          - Qism / Bo'lim / Bob / Paragraf sarlavhalari
  CLAUSE_DEFAULT               - "N-modda. Sarlavha"
  ACT_TEXT, TEXT_CENTER, ...   - matn xatboshilari
  CHANGES_ORIGINS              - "(... tahririda / ... bilan to'ldirilgan ...)" o'zgartirish izohi
  COMMENT (+COMMENTLEXUZ)      - "Oldingi tahrirga qarang" / LexUZ sharhi
  INDEXES_ON_REF               - klassifikator (OKOZ/TSZ)
  PUBLICATION_ORIGIN           - rasmiy manba
  SIGNATURE, ACT_ESSENTIAL_*   - imzo, joy, sana, raqam
Har element ichidagi `.lx_elem2` - sayt tugmalari ("Audioni tinglash" ...), olib tashlanadi.
"""
from __future__ import annotations

import copy
import csv
import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

from . import config
from .normalize import normalize_text, to_superscript
from .scraper import load_list_index, log_failure, raw_card_path, raw_doc_path

log = logging.getLogger(__name__)

SKIP_CLASSES = {"lx_elem", "lx_no_select"}
BODY_CLASSES = {"ACT_TEXT", "TEXT_CENTER", "TEXT_RIGHT", "TEXT_LEFT", "TABLE_STD", "BY_DEFAULT",
                "ACT_TEXT_SMALL", "TEXT_DEFAULT", "LIST_DEFAULT", "NOTE_DEFAULT", "ANNEX_DEFAULT",
                "TEXT_ITALIC", "TEXT_BOLD", "TABLE_DEFAULT", "FORMULA", "IMAGE", "EXPLANATION"}
SIGN_CLASSES = {"SIGNATURE", "ACT_ESSENTIAL_ELEMENTS", "ACT_ESSENTIAL_ELEMENTS_NUM", "SIGNATURE_RIGHT"}

QUOTES = "“\"«„'‘"
SUPS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
ART_RE = re.compile(rf"^(\d+[{SUPS}]*)\s*-\s*modda\b\.?\s*(.*)$", re.S | re.I)
SECTION_RE = re.compile(r"\bBO.?LIM\b", re.I)
CHAPTER_RE = re.compile(rf"^(\d+[{SUPS}]*|[IVXLC]+)\s*-?\s*BOB\b", re.I)
PARAGRAPH_RE = re.compile(r"§")
PART_RE = re.compile(r"^(UMUMIY|MAXSUS|YAKUNIY|KIRISH|ALOHIDA)?\s*QISM\b", re.I)

# Matn ichida qolib ketgan o'zgartirish izohlari
INLINE_AMEND_RE = re.compile(
    r"\((?:[^()]|\([^()]*\)){0,600}?"
    r"(?:tahririda|bilan oʻzgartirilgan|bilan toʻldirilgan|chiqarib tashlangan|kuchini yoʻqotgan"
    r"|oʻz kuchini yoʻqotgan|asosan oʻzgartirilgan|asosan toʻldirilgan)"
    r"(?:[^()]|\([^()]*\)){0,600}?\)"
)
AMEND_HINT_RE = re.compile(r"(-son|milliy bazasi|Qonun|Farmon|qarori|Axborotnomasi|toʻplami)", re.I)

# kartochka ba'zan ruscha, ba'zan o'zbekcha keladi; tartib muhim ("amalda emas" "amalda" dan oldin)
STATUS_MAP_RAW = [("не действ", "amalda emas"), ("amalda emas", "amalda emas"), ("утрат", "kuchini yo'qotgan"),
                  ("kuchini yo", "kuchini yo'qotgan"), ("не вступ", "kuchga kirmagan"), ("kuchga kirmagan", "kuchga kirmagan"),
                  ("приостан", "to'xtatilgan"), ("действ", "amalda"), ("amalda", "amalda")]
ORGAN_RU = {
    "олий мажлис республики узбекистан": "Oʻzbekiston Respublikasi Oliy Majlisi",
    "верховный совет республики узбекистан": "Oʻzbekiston Respublikasi Oliy Kengashi",
    "верховный совет узбекской сср": "Oʻzbekiston SSR Oliy Kengashi",
    "законодательная палата олий мажлиса республики узбекистан": "Oliy Majlis Qonunchilik palatasi",
    "сенат олий мажлиса республики узбекистан": "Oliy Majlis Senati",
}
FORM_RU = {"закон": "Qonun", "кодекс": "Kodeks", "конституционный закон": "Konstitutsiyaviy qonun",
           "конституция": "Konstitutsiya", "qonun": "Qonun", "kodeks": "Kodeks",
           "қонун": "Qonun", "кодекс": "Kodeks", "konstitutsiya": "Konstitutsiya",
           "конституция": "Konstitutsiya"}  # kartochka ba'zan o'zbek kirillida

UZ_MONTHS = {"yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6, "iyul": 7,
             "avgust": 8, "sentabr": 9, "sentyabr": 9, "oktabr": 10, "oktyabr": 10, "noyabr": 11,
             "dekabr": 12}


# ---------------------------------------------------------------- yordamchilar
def dmy_to_iso(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
    except ValueError:
        return None


def element_text(el: Tag) -> str:
    """Element matni: tugmalar olib tashlanadi, <sup> -> ¹, jadval -> 'a | b' qatorlari."""
    el = copy.copy(el)
    for junk in el.select(".lx_elem2, script, style, img"):
        junk.decompose()
    for sup in el.find_all("sup"):
        t = sup.get_text("", strip=True)
        sup.replace_with(NavigableString(to_superscript(t) if t.isdigit() else t))
    for br in el.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for table in el.find_all("table"):
        lines = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            if cells:
                lines.append(" | ".join(cells))
        table.replace_with(NavigableString("\n" + "\n".join(lines) + "\n"))
    for blk in el.find_all(["p", "div", "li", "tr"]):
        blk.insert_after(NavigableString("\n"))
    return normalize_text(el.get_text(""))


def role_of(el: Tag) -> str:
    cls = [c for c in (el.get("class") or []) if c not in SKIP_CLASSES]
    return cls[0] if cls else ""


def anchor_of(el: Tag) -> str | None:
    d = el.find(attrs={"id": re.compile(r"^-?\d+$")})
    return d["id"] if d else None


def heading_level(text: str) -> tuple[int, str]:
    t = text.strip()
    if t.startswith("Ilova"):
        return 0, "ilova"
    if PART_RE.search(t) and len(t) < 60:
        return 0, "qism"
    if SECTION_RE.search(t[:40]):
        return 1, "bolim"
    if CHAPTER_RE.search(t):
        return 2, "bob"
    if PARAGRAPH_RE.search(t[:15]):
        return 3, "paragraf"
    return 2, "sarlavha"


def _art_key(num: str) -> tuple[int, int]:
    base = int(re.match(r"\d+", num).group(0))
    sup = num[len(str(base)):].translate(str.maketrans(SUPS, "0123456789"))
    return base, int(sup) if sup.isdigit() else 0


def _is_next_article(prev: str | None, cur: str) -> bool:
    """cur moddasi prev dan keyin keladigan modda bo'la oladimi (2->3, 11->11¹, 11¹->11², 11¹->12)."""
    cb, cs = _art_key(cur)
    if prev is None:
        return cb == 1 and cs == 0
    pb, ps = _art_key(prev)
    return (cb == pb + 1 and cs == 0) or (cb == pb and cs == ps + 1)


def split_inline_amendments(text: str) -> tuple[str, list[str]]:
    found = []

    def _cut(m):
        s = m.group(0)
        if AMEND_HINT_RE.search(s):
            found.append(s)
            return ""
        return s

    out = INLINE_AMEND_RE.sub(_cut, text)
    return normalize_text(out), found


# ---------------------------------------------------------------- kartochka
def parse_card(html: str) -> dict:
    s = BeautifulSoup(html, "lxml")
    out = {}
    for td in s.select("td.lbl"):
        label = " ".join(td.get_text(" ", strip=True).split())
        val_td = td.find_next_sibling("td")
        if val_td is not None:
            out[label] = " ".join(val_td.get_text(" ", strip=True).split())
    organs = []
    for tr in s.select("#bodyTBody tr"):
        tds = [" ".join(t.get_text(" ", strip=True).split()) for t in tr.find_all("td")]
        if len(tds) >= 7:
            organs.append({"organ": tds[1], "signer_post": tds[2], "signer": tds[3],
                           "date": tds[4], "number": tds[5], "place": tds[6]})
    out["_organs"] = organs
    return out


def _map_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = normalize_text(raw).lower().replace("ʻ", "'").replace("ʼ", "'")
    for k, v in STATUS_MAP_RAW:
        if k in low:
            return v
    return raw


# ---------------------------------------------------------------- asosiy parser
def parse_document(lex_id: str, row: dict | None = None) -> dict:
    html = raw_doc_path(lex_id).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    cont = soup.find(id="divCont")
    if cont is None:
        raise ValueError("divCont topilmadi")

    # --- sarlavha qismi (docHeader)
    hdr = soup.select_one(".docHeader__col__1 .docHeader__item-label")
    requisites = normalize_text(hdr.get_text(" ", strip=True)) if hdr else (row or {}).get("requisites", "")
    eif = soup.select_one(".docHeader__col__2 .docHeader__item-value")
    entry_into_force = dmy_to_iso(eif.get_text(" ", strip=True)) if eif else None
    sel = soup.select_one(".lx_date_selected")
    editions = [dmy_to_iso(x.get_text(strip=True)) for x in soup.select(".lx_date_link")
                if "ONDATE=" in (x.get("onclick") or "")]
    last_edition = dmy_to_iso(sel.get_text(strip=True)) if sel else None

    # --- matn elementlari
    title = form = None
    grif, signature, publication, classifiers, lexuz_notes = [], [], [], [], []
    amendments: list[dict] = []
    blocks: list[dict] = []          # {"kind": heading|article|para, ...}
    unknown = Counter()
    path = {}                         # level -> heading text
    cur_article = None
    last_art_num = None
    is_amending_law = False

    def current_unit_label():
        if cur_article:
            return f"{cur_article['number']}-modda"
        return " > ".join(path[k] for k in sorted(path)) or "preambula"

    for el in cont.find_all("div", recursive=False):
        role = role_of(el)
        if not role:
            continue
        if role == "COMMENT":
            if el.select_one(".COMMENTLEXUZ"):
                c = copy.copy(el)
                for x in c.select(".COMMENTLEXUZ"):
                    x.decompose()
                t = element_text(c)
                if t:
                    lexuz_notes.append({"unit": current_unit_label(), "text": t})
            continue  # "Oldingi tahrirga qarang" - kerak emas
        if role == "CHANGES_ORIGINS":
            t = element_text(el)
            if t:
                amendments.append({"unit": current_unit_label(), "anchor": anchor_of(el),
                                   "article": cur_article["number"] if cur_article else None, "text": t})
                if cur_article is not None:
                    cur_article["amendments"].append(t)
            continue
        if role == "INDEXES_ON_REF":
            d = el.find(attrs={"id": re.compile(r"^on(LBC|LS)")})
            if d and d["id"].endswith(lex_id):
                classifiers.append(normalize_text(d.get_text(" ", strip=True)).strip("[]"))
            continue
        if role in ("PUBLICATION_ORIGIN", "OFFICIAL_SOUR_TEXT"):
            t = element_text(el)
            if t:
                publication.append(t)
            continue

        text = element_text(el)
        if role in ("ACT_FORM", "ACCEPTING_BODY", "ACT_FORM_LAW"):
            if text:
                form = f"{form} {text}".strip() if form else text
            continue
        if role == "ACT_TITLE":
            title = " ".join(text.split()) or title  # sarlavha ichidagi qator uzilishlari
            is_amending_law = bool(re.search(r"oʻzgartirish|qoʻshimcha", title or "", re.I))
            continue
        if role.startswith("GRIF"):
            if text:
                grif.append(text)
            continue
        if role in SIGN_CLASSES:
            if text:
                signature.append(text)
            continue
        if not text or role == "NEW_EDITION":
            continue

        anchor = anchor_of(el)
        quoted = text[:1] in QUOTES
        # Ilova (qonunga ilova qilingan nizom, ro'yxat va h.k.): o'z moddalar raqamlanishi 1 dan boshlanadi
        if role.startswith("APPL_") or role == "ACT_TITLE_APPL":
            if role == "ACT_TITLE_APPL":
                label = f"Ilova: {text}"
            else:
                label = "Ilova"
            path.clear()
            path[0] = label
            cur_article, last_art_num = None, None
            if blocks and blocks[-1]["kind"] == "heading" and blocks[-1]["htype"] == "ilova":
                blocks[-1]["text"] = label  # banner + sarlavha -> bitta sarlavha
            else:
                blocks.append({"kind": "heading", "level": 0, "htype": "ilova", "text": label, "anchor": anchor})
            continue
        # Sarlavha. O'zgartirish qonunida modda ichidagi (yoki qo'shtirnoqdagi) sarlavha -
        # boshqa qonunga kiritilayotgan matn, shuning uchun u modda matni bo'lib qoladi.
        if role == "TEXT_HEADER_DEFAULT" and not quoted and not (is_amending_law and cur_article is not None):
            lvl, kind = heading_level(text)
            for k in [k for k in path if k >= lvl]:
                del path[k]
            path[lvl] = text
            cur_article = None
            blocks.append({"kind": "heading", "level": lvl, "htype": kind, "text": text, "anchor": anchor})
            continue

        # Modda boshi?
        m = ART_RE.match(text)
        start_article = False
        if m and not quoted:
            sequential = _is_next_article(last_art_num, m.group(1))
            if role == "CLAUSE_DEFAULT":
                # oddiy qonunda o'chirilgan moddalar sabab raqamda bo'shliq bo'lishi mumkin;
                # o'zgartirish qonunida esa ketma-ket bo'lmagan modda - iqtibos
                start_article = sequential or not is_amending_law
            else:
                # ACT_TEXT ichidagi "N-modda. ..." - faqat ketma-ketlik saqlansa (iqtibos emas)
                start_article = sequential
        if start_article:
            num, rest = m.group(1), m.group(2).strip()
            art_title = rest if role == "CLAUSE_DEFAULT" else ""
            first_para = "" if role == "CLAUSE_DEFAULT" else rest
            cur_article = {"kind": "article", "number": num, "title": art_title, "anchor": anchor,
                           "path": [path[k] for k in sorted(path)], "paras": [], "amendments": []}
            if first_para:
                cur_article["paras"].append(first_para)
            blocks.append(cur_article)
            last_art_num = num
            continue

        if role not in BODY_CLASSES and role not in ("CLAUSE_DEFAULT", "FOOTNOTE") and not role.startswith(("TABLE", "TEXT_")):
            unknown[role] += 1
        clean, inl = split_inline_amendments(text)
        for a in inl:
            amendments.append({"unit": current_unit_label(), "anchor": anchor,
                               "article": cur_article["number"] if cur_article else None, "text": a})
            if cur_article is not None:
                cur_article["amendments"].append(a)
        if not clean:
            continue
        if cur_article is not None:
            cur_article["paras"].append(clean)
        else:
            blocks.append({"kind": "para", "text": clean, "anchor": anchor,
                           "path": [path[k] for k in sorted(path)]})

    # --- kartochka
    card = {}
    cp = raw_card_path(lex_id)
    if cp.exists():
        try:
            card = parse_card(cp.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning("%s: kartochka parse xatosi %s", lex_id, e)
    organs = card.get("_organs") or []
    organ_ru = organs[0]["organ"] if organs else None
    organ_uz = ORGAN_RU.get((organ_ru or "").lower().strip(), normalize_text(organ_ru) if organ_ru else None)

    # raqam va sana (rekvizitdan): "Oʻzbekiston Respublikasining Qonuni, 21.10.2026 yildagi OʻRQ-1184-son"
    number = None
    nums = re.findall(r"(\S+?)-son(?:li)?\b", requisites)
    if nums:
        number = nums[-1].strip(" -,")
    elif organs and organs[0]["number"]:
        number = organs[0]["number"]
    adoption = dmy_to_iso(requisites) or dmy_to_iso(organs[0]["date"] if organs else None)
    doc_type_uz = None
    m2 = re.match(r"^(.*?)(?:,|\s+\d{2}\.\d{2}\.\d{4})", requisites)
    if m2:
        doc_type_uz = m2.group(1).strip()
    form_ru = card.get("Форма акта")
    doc_type = FORM_RU.get((form_ru or "").lower(), form_ru) or "Qonun"

    # asosiy manba - ro'yxatdagi holat belgisi (lex.uz'ning o'z 3 toifasi), zaxira - kartochka
    status = (row or {}).get("list_status") or _map_status(card.get("Статус акта"))

    # --- toza to'liq matn
    lines = []
    for b in blocks:
        if b["kind"] == "heading":
            lines.append(b["text"])
        elif b["kind"] == "para":
            lines.append(b["text"])
        else:
            lines.append(f"{b['number']}-modda. {b['title']}".rstrip(". ") if b["title"] else f"{b['number']}-modda.")
            lines.extend(b["paras"])
    full_text = "\n".join(lines)

    signed_id = lex_id
    doc = {
        "id": signed_id.lstrip("-"),
        "lex_id": signed_id,
        "title": title or " ".join(((row or {}).get("title") or "").split()),
        "doc_type": doc_type,
        "doc_type_full": doc_type_uz or form,
        "number": number,
        "adoption_date": adoption,
        "issuing_body": organ_uz,
        "issuing_body_raw": organ_ru,
        "signer": (organs[0]["signer_post"] + " " + organs[0]["signer"]).strip() if organs else None,
        "status": status,
        "status_raw": card.get("Статус акта"),
        "entry_into_force_date": entry_into_force or dmy_to_iso(card.get("Дата вступления в силу")),
        "expiry_date": dmy_to_iso(card.get("Дата прекращения действия")),
        # lex.uz tahrirlar ro'yxatidagi eng oxirgi (tanlangan) sana; tahrirlar bo'lmasa - asl matn
        "last_edition_date": last_edition or (editions[0] if editions else None) or entry_into_force or adoption,
        "edition_source": "tahrirlar ro'yxati" if (last_edition or editions) else "asl tahrir",
        "n_editions": len(editions) + (1 if sel else 0),
        "url": config.DOC_URL.format(lex_id=signed_id),
        "language": "uz-Latn",
        "requisites": requisites,
        "grif": grif,
        "publication_source": publication,
        "classifiers": classifiers,
        "signature": signature,
        # boshqa qonunlarga o'zgartirish kirituvchi qonun (matni asosan "... so'zlar bilan almashtirilsin")
        "is_amending_law": is_amending_law,
        "collection": (row or {}).get("collection", "qonun"),
        "n_articles": sum(1 for b in blocks if b["kind"] == "article"),
        "n_chars": len(full_text),
        "text": full_text,
        "structure": blocks,
        "amendments": amendments,
        "lexuz_notes": lexuz_notes,
        "unknown_roles": dict(unknown),
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
    }
    return doc


META_FIELDS = ["id", "lex_id", "collection", "title", "doc_type", "number", "adoption_date", "issuing_body", "status",
               "entry_into_force_date", "last_edition_date", "url", "language", "is_amending_law", "n_articles", "n_chars",
               "n_amendments", "quality_flag"]

SHORT_TEXT_CHARS = 500


def quality_flag(doc: dict) -> str:
    if doc["n_chars"] == 0:
        return "empty"
    if doc["n_chars"] < SHORT_TEXT_CHARS:
        return "very_short"
    return "ok"


def parse_all(rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else load_list_index()
    ok = fail = 0
    meta = []
    for r in tqdm(rows, desc="parse"):
        lid = r["lex_id"]
        if not raw_doc_path(lid).exists():
            continue
        try:
            doc = parse_document(lid, r)
            doc["quality_flag"] = quality_flag(doc)
            out = config.CLEAN / f"{doc['id']}.json"
            out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            m = {k: doc.get(k) for k in META_FIELDS}
            m["n_amendments"] = len(doc["amendments"])
            meta.append(m)
            ok += 1
        except Exception as e:  # noqa: BLE001
            log.exception("%s parse xatosi", lid)
            log_failure("parse", lid, repr(e))
            fail += 1
    write_metadata_csv()
    return {"parsed": ok, "parse_failed": fail}


def write_metadata_csv():
    """data/clean/ dagi barcha hujjatlardan metadata.csv ni qayta yozadi."""
    rows = []
    for p in sorted(config.CLEAN.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        m = {k: d.get(k) for k in META_FIELDS}
        m["n_amendments"] = len(d.get("amendments", []))
        rows.append(m)
    with open(config.METADATA_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=META_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)
