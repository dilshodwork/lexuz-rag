"""report.md: yig'ish, parse va chunking statistikasi hamda tekshiruv natijalari."""
from __future__ import annotations

import csv
import json
import statistics as st
from collections import Counter
from datetime import datetime

from . import config
from .parser import SHORT_TEXT_CHARS
from .scraper import load_list_index, raw_doc_path


def _failures() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if config.FAILURES.exists():
        for line in config.FAILURES.read_text(encoding="utf-8").splitlines():
            if line.strip():
                f = json.loads(line)
                out.setdefault(f["lex_id"], []).append(f)
    return out


def _pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "-"


def build_report() -> str:
    rows = load_list_index()
    by_lex = {r["lex_id"]: r for r in rows}
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.CLEAN.glob("*.json"))]
    have = {d["lex_id"] for d in docs}
    fails = _failures()

    sample_file = config.STATE / "sample_ids.json"
    sample = set(json.loads(sample_file.read_text())) if sample_file.exists() else set()
    sample_mode = bool(docs) and len(docs) < len(rows) and have <= sample
    scope = [r for r in rows if r["lex_id"] in sample] if sample_mode else rows

    missing = []
    for r in scope:
        if r["lex_id"] in have:
            continue
        f = fails.get(r["lex_id"])
        if f:
            reason = f"{f[-1]['stage']}: {f[-1]['error']}"
        elif not raw_doc_path(r["lex_id"]).exists():
            reason = "hali yuklanmagan (raw yo'q)"
        else:
            reason = "raw bor, lekin parse qilinmagan"
        missing.append({**r, "reason": reason})
    with open(config.DATA / "missing.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pos", "lex_id", "title", "url", "list_status", "reason"])
        w.writeheader()
        for m in missing:
            w.writerow({k: m.get(k) for k in w.fieldnames})

    flagged = [d for d in docs if d.get("quality_flag") != "ok"]
    no_articles = [d for d in docs if d["n_articles"] == 0]

    chunks = []
    if config.CHUNKS.exists():
        with open(config.CHUNKS, encoding="utf-8") as fh:
            chunks = [json.loads(l) for l in fh if l.strip()]
    toks = [c["n_tokens"] for c in chunks]
    buckets = Counter()
    for t in toks:
        b = "<100" if t < 100 else "100-299" if t < 300 else "300-800" if t <= 800 else ">800"
        buckets[b] += 1

    verify = []
    vf = config.STATE / "verify.json"
    if vf.exists():
        verify = json.loads(vf.read_text(encoding="utf-8"))

    L = []
    L.append("# lex.uz \"Qonunlar\" - RAG baza hisoboti\n")
    L.append(f"Yaratilgan: {datetime.now():%Y-%m-%d %H:%M}\n")
    if sample_mode:
        L.append(f"**Rejim: sinov namunasi ({len(scope)} ta hujjat).** To'liq yig'ish hali ishga tushirilmagan.\n")
    L.append("## 1. Yig'ish\n")
    L.append("| Ko'rsatkich | Qiymat |\n|---|---|")
    clean_by = Counter(d.get("collection", "qonun") for d in docs)
    for name, spec in config.COLLECTIONS.items():
        got = sum(1 for r in rows if r.get("collection", "qonun") == name)
        ok = "mos" if got == spec["expected"] else "MOS EMAS"
        L.append(f"| {name}: saytda / ro'yxatda / tozalangan | {spec['expected']} / {got} ({ok}) / {clean_by[name]} |")
    L.append(f"| Jami: saytda / ro'yxatda | {config.EXPECTED_TOTAL} / {len(rows)} |")
    if sample_mode:
        L.append(f"| Namunadagi hujjatlar | {len(scope)} |")
    L.append(f"| Tozalangan hujjatlar (data/clean) | {len(docs)} ({_pct(len(docs), len(scope))}) |")
    L.append(f"| Chiqmagan hujjatlar | {len(missing)} (ro'yxat: data/missing.csv) |")
    L.append("")
    if missing:
        reasons = Counter(m["reason"].split(":")[0] for m in missing)
        L.append("Chiqmaganlar sababi bo'yicha: " + ", ".join(f"{k}: {v}" for k, v in reasons.most_common()) + "\n")
        for m in missing[:30]:
            L.append(f"- [{m['title'][:90]}]({m['url']}) - {m['reason'][:150]}")
        if len(missing) > 30:
            L.append(f"- ... yana {len(missing) - 30} ta (data/missing.csv)")
        L.append("")

    if docs:
        L.append("## 2. Hujjatlar\n")
        st_c = Counter(d["status"] for d in docs)
        L.append("Holati: " + ", ".join(f"{k}: {v}" for k, v in st_c.most_common()) + "\n")
        dt_c = Counter(d["doc_type"] for d in docs)
        L.append("Turi: " + ", ".join(f"{k}: {v}" for k, v in dt_c.most_common()) + "\n")
        chars = [d["n_chars"] for d in docs]
        L.append(f"Matn uzunligi (belgi): o'rtacha {st.mean(chars):,.0f}, mediana {st.median(chars):,.0f}, "
                 f"min {min(chars):,}, max {max(chars):,}\n")
        L.append(f"Moddalar jami: {sum(d['n_articles'] for d in docs):,}; "
                 f"o'zgartirish izohlari (alohida maydonga ajratilgan): {sum(len(d['amendments']) for d in docs):,}; "
                 f"LexUZ sharhlari: {sum(len(d['lexuz_notes']) for d in docs):,}\n")
        unk = Counter()
        for d in docs:
            unk.update(d.get("unknown_roles", {}))
        if unk:
            L.append("Parser tanimagan element klasslari (matnga qo'shildi): "
                     + ", ".join(f"{k}: {v}" for k, v in unk.most_common()) + "\n")
        L.append(f"### Bo'sh yoki juda qisqa matnli hujjatlar (< {SHORT_TEXT_CHARS} belgi): {len(flagged)}\n")
        no_art_short = sum(1 for d in flagged if d["n_articles"] == 0)
        L.append(f"Ulardan {no_art_short} tasi moddasiz hujjat (asosan xalqaro shartnomani ratifikatsiya qilish "
                 "yoki unga qo'shilish haqidagi bir-ikki gaplik qonunlar). To'liq ro'yxat: data/short_docs.csv\n")
        with open(config.DATA / "short_docs.csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "quality_flag", "n_chars", "n_articles", "title", "url"])
            for d in flagged:
                w.writerow([d["id"], d["quality_flag"], d["n_chars"], d["n_articles"], d["title"], d["url"]])
        for d in flagged[:40]:
            L.append(f"- `{d['quality_flag']}` {d['n_chars']} belgi - [{d['title'][:90]}]({d['url']})")
        if len(flagged) > 40:
            L.append(f"- ... yana {len(flagged) - 40} ta (data/short_docs.csv)")
        L.append("")
        L.append(f"Moddasiz hujjatlar (masalan, ratifikatsiya qonunlari, matn butunligicha chunk bo'ladi): {len(no_articles)}\n")

    if chunks:
        L.append("## 3. Chunking\n")
        L.append("| Ko'rsatkich | Qiymat |\n|---|---|")
        L.append(f"| Chunklar soni | {len(chunks):,} |")
        L.append(f"| Hujjatga o'rtacha | {len(chunks) / max(1, len(docs)):.1f} |")
        L.append(f"| Token (bge-m3): o'rtacha / mediana | {st.mean(toks):.0f} / {st.median(toks):.0f} |")
        L.append(f"| Token: min / max | {min(toks)} / {max(toks)} |")
        chars_c = [len(c["text"]) for c in chunks]
        L.append(f"| Belgi: o'rtacha | {st.mean(chars_c):.0f} |")
        for b in ["<100", "100-299", "300-800", ">800"]:
            L.append(f"| {b} token | {buckets[b]:,} ({_pct(buckets[b], len(chunks))}) |")
        ut = Counter(c["unit_type"] for c in chunks)
        L.append(f"| Birlik turi | " + ", ".join(f"{k}: {v}" for k, v in ut.most_common()) + " |")
        L.append(f"| Bir nechta bo'lakka bo'lingan moddalar | "
                 f"{len({(c['doc_id'], c['article_number']) for c in chunks if c['n_chunks_in_unit'] > 1 and c['article_number']})} |")
        L.append("")

    if verify:
        L.append("## 4. Saytdagi asl matn bilan solishtirish\n")
        L.append("Jonli sahifa qayta yuklanib, `#divCont` ning butun matni (parserdan mustaqil, selectolax bilan) "
                 "bizning natija bilan so'zma-so'z solishtirildi.\n")
        L.append("| Hujjat | Saytdagi so'zlar | Recall | Precision | raw == jonli |\n|---|---|---|---|---|")
        for v in verify:
            L.append(f"| [{v['title'][:60]}]({v['url']}) | {v['live_words']:,} | {v['recall']:.3f} | "
                     f"{v['precision']:.3f} | {'ha' if v['raw_same_as_live'] else 'yo`q'} |")
        L.append("")
        L.append("Recall - saytdagi so'zlarning bizdagi ulushi (matn + izohlar + rekvizitlar). "
                 "Precision - bizning asosiy matn so'zlarining saytda borligi.\n")

    text = "\n".join(L) + "\n"
    if (config.STATE / "colab_import.json").exists() or (config.INDEX_DIR / "chroma").exists():
        try:
            from .indexer import get_collection
            col = get_collection("BAAI/bge-m3", create=False)
            n_idx = col.count()
        except Exception:  # noqa: BLE001
            n_idx = None
        extra = ["## 5. Vektor baza\n", "| Ko'rsatkich | Qiymat |\n|---|---|",
                 "| Model | BAAI/bge-m3 (1024 o'lcham, CLS pooling, L2 normalizatsiya, fp32) |",
                 "| Baza | ChromaDB, cosine, data/index/chroma, kolleksiya `lex_qonunlar` |",
                 f"| Indeksdagi chunklar | {n_idx if n_idx is not None else '-'} (chunks.jsonl: {len(chunks)}) |"]
        ci = config.STATE / "colab_import.json"
        if ci.exists():
            c = json.loads(ci.read_text(encoding="utf-8"))
            extra.append("| Hisoblangan joyi | Google Colab T4 GPU (embedding), qidiruv shu kompyuterda ONNX bilan |")
            extra.append(f"| Mahalliy ONNX vs Colab, {c['checked']} tasodifiy chunk | cosine min {c['cos_min']:.6f}, "
                         f"o'rtacha {c['cos_mean']:.6f} |")
        text += "\n".join(extra) + "\n"
    from .evaluate import report_section  # 6. Baholash (eval/results.json bo'lsa)
    if sec := report_section():
        text += "\n" + sec
    config.REPORT.write_text(text, encoding="utf-8")
    return text
