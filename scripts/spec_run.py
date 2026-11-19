"""Tester tomoni: "RAG API — test spetsifikatsiyasi (lex.uz)" 1- va 6-bo'limlari bo'yicha run.

Ustoz qanday tekshirsa, shunday: 100 savollik CSV -> 10 ta batch, ketma-ket POST /v1/rag/batch, har javob
<out>/<run_id>/bNN.json ga saqlanadi, keyin 6-bo'lim metrikalari hisoblanadi (report.json + report.md).

    # 1) test to'plami (eval/questions.jsonl dan, spetsifikatsiya CSV formatida)
    .venv/bin/python scripts/spec_run.py build --out eval/spec_testset.csv

    # 2) run (kalit muhit o'zgaruvchisida; chop etilmaydi)
    RAG_TEST_KEY=... python scripts/spec_run.py run --url https://92-5-109-49.sslip.io \
        --csv eval/spec_testset.csv --run-id eval-2026-11-19 [--batches b01,b02]

    # 3) saqlangan javoblardan metrikalarni qayta hisoblash (LLM'siz)
    python scripts/spec_run.py score --csv eval/spec_testset.csv --dir eval/spec_runs/eval-2026-11-19

Faqat stdlib + httpx (Docker image ichida ham ishlaydi).
Avtomatik hisoblanmaydi (LLM-hakam yoki qo'lda kerak): Answer correctness, Faithfulness. Citation accuracy va
Context precision - taqribiy (kutilgan modda/hujjat bo'yicha), report'da shunday belgilangan.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["id", "batch", "category", "question", "expected_answer", "expected_doc_id", "expected_article",
          "answerable", "language", "source"]
NUM_RE = re.compile(r"\b(qancha|necha|muddat|foiz|miqdor|summa|yosh|kun|oy|yil|сколько|срок|қанча|неча|муддат)",
                    re.I)
# eval/questions.jsonl da 9 ta "bazada yo'q" savol bor; spetsifikatsiya 10 ta so'raydi
EXTRA_NO = [{"id": "x01", "question": "Fransiyada qoʻshilgan qiymat soligʻining asosiy stavkasi necha foiz?",
             "lang": "uz", "split": "extra", "gold": [], "category": "bazada yoʻq"}]


# ---------------------------------------------------------------- build
def build(out: Path, seed: int):
    qs = [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").open(encoding="utf-8")]
    rng = random.Random(seed)
    no = [q for q in qs if not q.get("gold")] + EXTRA_NO
    test = [q for q in qs if q.get("gold") and q["split"] == "test"]
    dev = [q for q in qs if q.get("gold") and q["split"] == "dev"]
    rng.shuffle(dev)
    ans = test + dev[: 90 - len(test)]  # TEST (sozlashda qaralmagan) birinchi, yetmaganini DEV'dan

    def cat(q):
        if not q.get("gold"):
            return "javobsiz"
        if len(q["gold"]) > 1:
            return "bir_nechta_modda"
        if q["lang"] != "uz":
            return "rus_kirill"
        if NUM_RE.search(q["question"]):
            return "raqamlar"
        return "faktik"
    rows = []
    for q in ans + no[:10]:
        g = q.get("gold") or []
        rows.append({"id": "", "batch": "", "category": cat(q), "question": q["question"], "expected_answer": "",
                     "expected_doc_id": "|".join(dict.fromkeys(f"lex:{x['doc_id']}" for x in g)),
                     "expected_article": "|".join(f"lex:{x['doc_id']}#{x['article']}-modda" for x in g),
                     "answerable": "true" if g else "false",
                     "language": {"uz": "uz-Latn", "uz_cyr": "uz-Cyrl", "ru": "ru"}.get(q["lang"], ""),
                     "source": f"{q['split']}:{q['id']}"})
    # har batch'ga har kategoriyadan aralash (spetsifikatsiya 6-bo'lim): kategoriya bo'yicha tartiblab,
    # navbat bilan 10 batch'ga tarqatiladi - har kategoriya batch'lar bo'ylab teng taqsimlanadi
    order = {"javobsiz": 0, "bir_nechta_modda": 1, "rus_kirill": 2, "raqamlar": 3, "faktik": 4}
    rng.shuffle(rows)
    rows.sort(key=lambda r: order[r["category"]])
    batches = [[] for _ in range(10)]
    for i, r in enumerate(rows):
        batches[i % 10].append(r)
    for items in batches:
        rng.shuffle(items)
    n = 0
    final = []
    for b, items in enumerate(batches, 1):
        for r in items:
            n += 1
            final.append({**r, "id": f"q{n:03d}", "batch": f"b{b:02d}"})
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(final)
    cnt: dict[str, int] = {}
    for r in final:
        cnt[r["category"]] = cnt.get(r["category"], 0) + 1
    print(f"{out}: {len(final)} savol, {len(batches)} batch; kategoriyalar: {cnt}")


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- run
def _post(c, url, body, headers, poll_s=5, max_wait=900):
    """Spetsifikatsiya 5-bo'lim: 202 -> GET poll; 429 -> Retry-After; 500/503/504 -> 5, 15, 45 s."""
    backoff = [5, 15, 45]
    err: Exception | None = None
    t_end = time.time() + max_wait
    while True:
        try:
            r = c.post(f"{url}/v1/rag/batch", content=json.dumps(body, ensure_ascii=False).encode(), headers=headers)
        except Exception as e:  # noqa: BLE001 - tarmoq xatosi: 5xx kabi
            r, err = None, e
        if r is not None and r.status_code == 429:
            time.sleep(float(r.headers.get("retry-after", "1")))
            continue
        if r is None or r.status_code in (500, 502, 503, 504):
            if not backoff:
                raise RuntimeError(f"batch {body['batch_id']}: {r.status_code if r else err}")
            time.sleep(backoff.pop(0))
            continue
        if r.status_code == 202:
            while time.time() < t_end:
                time.sleep(poll_s)
                g = c.get(f"{url}/v1/rag/batch/{body['batch_id']}", headers=headers)
                if g.status_code == 200 and g.json().get("status") != "processing":
                    return g.json()
            raise RuntimeError(f"batch {body['batch_id']}: async natija {max_wait} s da kelmadi")
        if r.status_code != 200:
            raise RuntimeError(f"batch {body['batch_id']}: HTTP {r.status_code} {r.text[:300]}")
        return r.json()


def run(a):
    import httpx
    key = os.environ.get(a.key_env, "")
    if not key:
        sys.exit(f"{a.key_env} muhit o'zgaruvchisi bo'sh")
    rows = load_csv(Path(a.csv))
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["batch"], []).append(r)
    names = sorted(groups)
    if a.batches:
        names = [b for b in names if b in a.batches.split(",")]
    out = Path(a.out) / a.run_id
    out.mkdir(parents=True, exist_ok=True)
    H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8"}
    with httpx.Client(timeout=180) as c:
        meta = c.get(f"{a.url}/v1/meta").json()
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        for b in names:  # ketma-ket: oldingi javob kelgach keyingisi
            body = {"run_id": a.run_id, "batch_id": f"{a.run_id}-{b}", "batch_index": int(b[1:]),
                    "total_batches": len(groups),
                    "options": {"top_k": a.top_k, "return_contexts": True, "return_debug": True, "temperature": 0,
                                "seed": 42, "answer_language": "auto"},
                    "items": [{"id": r["id"], "question": r["question"],
                               **({"language": r["language"]} if r.get("language") else {})} for r in groups[b]]}
            t0 = time.time()
            d = _post(c, a.url, body, H)
            for attempt in range(a.retries):  # retryable savol xatolari: o'sha batch_id bilan qayta
                if not any(x["status"] in ("error", "timeout") and (x.get("error") or {}).get("retryable")
                           for x in d.get("results", [])):
                    break
                time.sleep([5, 15, 45][min(attempt, 2)])
                d = _post(c, a.url, body, H)
            d["_client_wall_s"] = round(time.time() - t0, 1)
            (out / f"{b}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{b}: {d.get('summary')} {d['_client_wall_s']} s", flush=True)
    score(Path(a.csv), out)


# ---------------------------------------------------------------- score
def _pct(x, n):
    return round(100 * x / n, 1) if n else None


def _p(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(round(q * len(s) + 0.5)) - 1))]  # nearest-rank


def score(csv_path: Path, d: Path):
    rows = {r["id"]: r for r in load_csv(csv_path)}
    res = {}
    systems = set()
    for f in sorted(d.glob("b[0-9][0-9].json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        systems.add(json.dumps(b.get("system"), sort_keys=True, ensure_ascii=False))
        for x in b.get("results", []):
            res[x["id"]] = x
    ids = [i for i in rows if i in res]
    if not ids:
        sys.exit("javoblar topilmadi")
    K = 5
    hit_doc = hit_art = 0
    rr = []
    prec = []
    cit_ok = cit_n = 0
    fabricated = outdated = 0
    lat, errors = [], 0
    na_ok = na_total = false_reject = 0
    by_cat: dict[str, dict] = {}
    causes = {"retrieval": [], "manba": [], "no_answer": [], "xato": []}
    for i in ids:
        r, x = rows[i], res[i]
        cat = by_cat.setdefault(r["category"], {"n": 0, "hit_art": 0, "rr": 0.0, "no_answer_ok": 0})
        cat["n"] += 1
        if (x.get("timing") or {}).get("total_ms") is not None:
            lat.append(x["timing"]["total_ms"])
        if x["status"] in ("error", "timeout"):
            errors += 1
            causes["xato"].append(i)
            continue
        ctx = sorted(x.get("contexts") or [], key=lambda c: c["rank"])
        ctx_ids = {c["chunk_id"] for c in ctx}
        for cit in x.get("citations") or []:
            if (cit.get("chunk_id") not in ctx_ids or not str(cit.get("doc_id", "")).startswith("lex:")
                    or "lex.uz/" not in str(cit.get("url", ""))):
                fabricated += 1
            if cit.get("doc_status") != "amalda":
                outdated += 1
        if r["answerable"] != "true":
            na_total += 1
            if x.get("no_answer"):
                na_ok += 1
                cat["no_answer_ok"] += 1
            else:
                causes["no_answer"].append(i)
            continue
        if x.get("no_answer"):
            false_reject += 1
        docs = set(filter(None, r["expected_doc_id"].split("|")))
        arts = set(filter(None, r["expected_article"].split("|")))

        def art_key(c):
            return f"{c.get('doc_id')}#{c.get('article')}"
        top = ctx[:K]
        if any(c.get("doc_id") in docs for c in top):
            hit_doc += 1
        ranks = [c["rank"] for c in ctx if art_key(c) in arts]
        first = min(ranks) if ranks else None
        if first is not None and first <= K:
            hit_art += 1
            cat["hit_art"] += 1
        rr.append(1 / first if first else 0.0)
        cat["rr"] += 1 / first if first else 0.0
        if top:
            prec.append(sum(c.get("doc_id") in docs for c in top) / len(top))
        cits = x.get("citations") or []
        if cits:
            cit_n += 1
            cit_ok += any(art_key(c) in arts for c in cits)
        if first is None or first > K:
            causes["retrieval"].append(i)
        elif cits and not any(art_key(c) in arts for c in cits):
            causes["manba"].append(i)
    n_ans = len(rr)
    rep = {
        "run_dir": str(d), "n_results": len(ids), "n_expected": len(rows), "answerable": n_ans,
        "unanswerable": na_total, "system_variants": len(systems),
        "systems": [json.loads(s) for s in systems],
        "metrics": {
            "hit@5_doc_%": _pct(hit_doc, n_ans), "hit@5_article_%": _pct(hit_art, n_ans),
            "mrr": round(sum(rr) / n_ans, 3) if n_ans else None,
            "context_precision_%_proxy_doc": round(100 * statistics.mean(prec), 1) if prec else None,
            "citation_accuracy_%_proxy_gold_article_cited": _pct(cit_ok, cit_n),
            "fabricated_citations": fabricated, "outdated_norm_citations": outdated,
            "no_answer_accuracy": f"{na_ok}/{na_total}", "false_reject_on_answerable": false_reject,
            "latency_ms_p50": _p(lat, 0.5), "latency_ms_p95": _p(lat, 0.95),
            "error_or_timeout_%": _pct(errors, len(ids)),
            "answer_correctness": "hisoblanmadi (expected_answer + LLM-hakam yoki qoʻlda)",
            "faithfulness": "hisoblanmadi (LLM-hakam kerak)"},
        "targets": {"hit@5_doc_%": ">= 90", "hit@5_article_%": ">= 80", "mrr": ">= 0.70",
                    "context_precision_%": ">= 60", "citation_accuracy_%": ">= 90", "fabricated_citations": "0",
                    "outdated_norm_citations": "0", "no_answer_accuracy": ">= 9/10", "latency_ms_p50": "<= 5000",
                    "latency_ms_p95": "<= 12000", "error_or_timeout_%": "<= 2"},
        "by_category": {k: ({"n": v["n"], "no_answer_ok": v["no_answer_ok"]} if k == "javobsiz" else
                            {"n": v["n"], "hit@5_article_%": _pct(v["hit_art"], v["n"]),
                             "mrr": round(v["rr"] / v["n"], 3)})
                        for k, v in sorted(by_cat.items())},
        "error_causes": causes,
    }
    (d / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    m, t = rep["metrics"], rep["targets"]
    lines = [f"# Spetsifikatsiya run: {d.name}", "", f"Javoblar: {len(ids)}/{len(rows)}; javobi bor {n_ans}, "
             f"javobsiz {na_total}; system variantlari: {len(systems)}", "", "| Metrika | Natija | Maqsad |",
             "|---|---|---|"]
    for k, v in m.items():
        tk = k.replace("_proxy_doc", "").replace("_proxy_gold_article_cited", "")
        lines.append(f"| {k} | {v} | {t.get(tk, '')} |")
    lines += ["", "Kategoriyalar: " + json.dumps(rep["by_category"], ensure_ascii=False), "",
              "Xato sababi (retrieval / manba / no_answer / xato): " +
              json.dumps({k: v for k, v in causes.items()}, ensure_ascii=False)]
    (d / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("--out", default=str(ROOT / "eval" / "spec_testset.csv"))
    b.add_argument("--seed", type=int, default=42)
    r = sp.add_parser("run")
    r.add_argument("--url", required=True)
    r.add_argument("--csv", default=str(ROOT / "eval" / "spec_testset.csv"))
    r.add_argument("--run-id", required=True)
    r.add_argument("--out", default=str(ROOT / "eval" / "spec_runs"))
    r.add_argument("--key-env", default="RAG_TEST_KEY")
    r.add_argument("--batches", help="masalan b01,b02 (standart: hammasi)")
    r.add_argument("--top-k", type=int, default=5)
    r.add_argument("--retries", type=int, default=1, help="retryable savol xatolarida batch'ni qayta yuborish")
    s = sp.add_parser("score")
    s.add_argument("--csv", default=str(ROOT / "eval" / "spec_testset.csv"))
    s.add_argument("--dir", required=True)
    a = ap.parse_args()
    if a.cmd == "build":
        build(Path(a.out), a.seed)
    elif a.cmd == "run":
        run(a)
    else:
        score(Path(a.csv), Path(a.dir))


if __name__ == "__main__":
    main()
