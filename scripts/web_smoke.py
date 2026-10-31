"""Ishlab turgan veb-serverni savollar bilan oxirigacha sinash (SSE /api/ask).

    .venv/bin/python scripts/web_smoke.py [--base http://127.0.0.1:8000] ["savol" ...]
"""
from __future__ import annotations

import argparse
import json
import re
import time

import httpx

DEFAULT_QS = [
    "Prezident qancha muddatga saylanadi?",
    "Yillik mehnat taʼtili necha kun?",
    "Ijara shartnomasi qanday shaklda tuziladi?",
    "Ажралиш учун қандай ҳужжатлар керак?",
    "Marsda yer sotib olish uchun qanday litsenziya kerak?",
]


def ask(base: str, q: str, filters: dict | None = None) -> dict:
    t0 = time.time()
    out = {"q": q, "sources": [], "text": "", "done": None, "error": None, "first_delta_s": None}
    body = {"question": q, **({"filters": filters} if filters else {})}
    with httpx.stream("POST", f"{base}/api/ask", json=body, timeout=300) as r:
        ev = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                d = json.loads(line[5:])
                if ev == "sources":
                    out["sources"] = d["sources"]
                    out["no_answer_pre"] = d["no_answer"]
                elif ev == "delta":
                    out["first_delta_s"] = out["first_delta_s"] or round(time.time() - t0, 1)
                    out["text"] += d["text"]
                elif ev == "done":
                    out["done"] = d
                elif ev == "error":
                    out["error"] = d
    out["total_s"] = round(time.time() - t0, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="*")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--json", help="natijalarni shu faylga yozish")
    a = ap.parse_args()
    results = []
    for q in a.questions or DEFAULT_QS:
        r = ask(a.base, q)
        results.append(r)
        cites = sorted({int(n) for n in re.findall(r"\[(\d+)\]", r["text"])})
        print(f"\n=== {q}")
        print(f"  manbalar: {len(r['sources'])}  "
              + "; ".join(f"[{s['n']}] {s['doc_type']} {s['article_number']}-m. cos={s['cosine']}" for s in r["sources"][:4]))
        print(f"  iqtiboslar: {cites}  birinchi bo'lak: {r['first_delta_s']}s  jami: {r['total_s']}s")
        print(f"  done: {r['done']}  error: {r['error']}")
        print("  javob: " + r["text"][:400].replace("\n", " "))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
