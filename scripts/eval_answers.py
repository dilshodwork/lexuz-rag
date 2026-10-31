"""Javob sifati (ixtiyoriy, LLM bilan): 5 ta savol -> eval/answers.json.

    .venv/bin/python scripts/eval_answers.py [--ids q02,q14,q28,c03,r01]

Har savolga aynan BITTA HTTP so'rov (llm._stream_once, qayta urinish va zaxira modelsiz) - limitni aniq sanash uchun.
Birinchi 429/503 da to'xtaydi va qolganini "o'tkazib yuborildi" deb yozadi.
O'lchanadi:
  * faithfulness - ishonch tekshiruvi (trust.check, /api/verify bilan bir xil): tasdiqlangan da'volar ulushi, daraja;
  * iqtibos to'g'riligi - [n] lar manbalar soni ichidami; gold modda iqtibos qilinganmi.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag import llm, rag, trust  # noqa: E402
from lexrag.evaluate import load_questions  # noqa: E402

DEFAULT_IDS = "q02,q14,q28,c03,r01"
OUT = ROOT / "eval" / "answers.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=DEFAULT_IDS)
    ap.add_argument("--max-requests", type=int, default=5)
    a = ap.parse_args()
    ids = a.ids.split(",")
    qs = {q["id"]: q for q in load_questions()}
    provider, model, key = llm.settings()
    items, requests, stopped = [], 0, None
    for qid in ids:
        q = qs[qid]
        p = rag.prepare(q["question"])
        gold = {(g["doc_id"], g["article"]) for g in q["gold"]}
        src_keys = [(s["chunk_id"].split("_", 1)[0], s["article_number"]) for s in p["sources"]]
        item = {"id": qid, "question": q["question"], "lang": p["lang"], "gold": q["gold"],
                "gold_in_sources": [i + 1 for i, k in enumerate(src_keys) if k in gold]}
        if p["no_answer"]:
            item.update(status="no_answer", note="qidiruv 'topilmadi' dedi, LLM chaqirilmadi")
            items.append(item)
            continue
        if stopped or requests >= a.max_requests:
            item.update(status="skipped", note=stopped or "so'rovlar limiti")
            items.append(item)
            continue
        requests += 1
        t0 = time.time()
        out = rag.AnswerStream(p["lang"])
        text, first = "", None
        try:
            for piece in llm._stream_once(provider, model, key, p["prompt"]["system"], p["prompt"]["user"], 0.1, 8192):
                first = first or time.time() - t0
                text += out.feed(piece)
            text += out.flush()
        except Exception as e:  # noqa: BLE001
            stopped = f"{type(e).__name__}: {str(e)[:160]}"
            item.update(status="error", note=stopped)
            items.append(item)
            print(f"XATO {qid}: {stopped}", flush=True)
            continue
        ids_ = [s["chunk_id"] for s in p["sources"]]
        tr = trust.check(text, ids_, p["lang"], "legal")
        cited = sorted({int(x) for m in re.finditer(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]", text)
                        for x in re.split(r"\s*[,;]\s*", m.group(1))})
        valid = [n for n in cited if 1 <= n <= len(ids_)]
        item.update(status="ok", model=model, answer=text, followups=out.followups(), not_found=out.not_found(),
                    first_token_s=round(first or 0, 2), total_s=round(time.time() - t0, 2),
                    trust={"level": tr["level"], "checked": tr["checked"], "supported": tr["supported"]},
                    faithfulness=round(tr["supported"] / tr["checked"], 3) if tr["checked"] else None,
                    cited=cited, cites_valid=len(valid) == len(cited),
                    gold_cited=any(src_keys[n - 1] in gold for n in valid))
        items.append(item)
        print(f"OK {qid}: ishonch {tr['level']} {tr['supported']}/{tr['checked']}, iqtibos {cited}, "
              f"gold iqtibos qilingan: {item['gold_cited']}", flush=True)
    ok = [i for i in items if i["status"] == "ok"]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    res = {"meta": {"created": datetime.now().astimezone().isoformat(timespec="seconds"), "commit": commit,
                    "provider": provider, "model": model, "llm_requests": requests, "stopped": stopped},
           "summary": {"n": len(items), "answered": len(ok),
                       "faithfulness": round(sum(i["faithfulness"] or 0 for i in ok) / len(ok), 3) if ok else None,
                       "trust_high": sum(i["trust"]["level"] == "high" for i in ok),
                       "cites_valid": sum(i["cites_valid"] for i in ok),
                       "gold_cited": sum(i["gold_cited"] for i in ok)},
           "items": items}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False), f"LLM so'rovlari: {requests}")


if __name__ == "__main__":
    main()
