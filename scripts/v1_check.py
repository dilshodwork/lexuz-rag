"""/v1 test API'ni spetsifikatsiya checklist'i bo'yicha tekshirish (7-bo'lim).

Ikki rejim:
    .venv/bin/python scripts/v1_check.py                 # lokal, LLM mock (kvota sarflanmaydi), FastAPI TestClient
    .venv/bin/python scripts/v1_check.py --url https://... --key-env RAG_TEST_KEY [--live-llm]
        haqiqiy server; --live-llm bo'lmasa faqat LLM chaqirmaydigan tekshiruvlar (validatsiya, auth, meta,
        health, javobsiz savol) bajariladi.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, FAIL = "\033[32mOK\033[0m", "\033[31mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, info: str = ""):
    results.append((name, bool(cond), info))
    print(f"[{OK if cond else FAIL}] {name}" + (f"  — {info}" if info and not cond else ""))


def batch(run: str, bid: str, items: list[dict], **opt) -> dict:
    return {"run_id": run, "batch_id": bid, "batch_index": 1, "total_batches": 1,
            "options": {"top_k": 5, "return_contexts": True, "return_debug": True, "temperature": 0, "seed": 42,
                        **opt}, "items": items}


QS = [
    {"id": "q001", "question": "Yillik asosiy mehnat taʼtilining eng kam muddati qancha?", "language": "uz-Latn"},
    {"id": "q002", "question": "Какой срок исковой давности установлен Гражданским кодексом?", "language": "ru"},
    {"id": "q003", "question": "Президент қанча муддатга сайланади?"},
    {"id": "q004", "question": "Marsda yer sotib olish tartibi qanday?"},
]


def run(client, key: str, live_llm: bool):
    H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8"}
    run_id = f"check-{uuid.uuid4().hex[:6]}"

    r = client.get("/v1/health")
    check("GET /v1/health ishlaydi", r.status_code == 200 and r.json().get("ok"), r.text[:200])
    r = client.get("/v1/meta")
    m = r.json() if r.status_code == 200 else {}
    check("GET /v1/meta: model, embedding, indeks versiyasi, snapshot sanasi",
          all(m.get(k) for k in ("llm_model", "embedding_model", "index_version", "lex_snapshot_date")), r.text[:300])
    check("Content-Type: application/json; charset=utf-8", "charset=utf-8" in r.headers.get("content-type", ""),
          r.headers.get("content-type", ""))

    # autentifikatsiya
    b = batch(run_id, f"{run_id}-auth", QS[:1])
    r = client.post("/v1/rag/batch", content=json.dumps(b), headers={"Content-Type": "application/json"})
    check("Kalitsiz so'rov -> 401", r.status_code == 401, str(r.status_code))
    r = client.post("/v1/rag/batch", content=json.dumps(b), headers={**H, "Authorization": "Bearer xato"})
    check("Noto'g'ri kalit -> 403", r.status_code == 403, str(r.status_code))

    # validatsiya
    many = [{"id": f"q{i:03d}", "question": "Savol?"} for i in range(11)]
    r = client.post("/v1/rag/batch", content=json.dumps(batch(run_id, f"{run_id}-11", many)), headers=H)
    check("11 ta savol -> 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
    r = client.post("/v1/rag/batch", content=json.dumps(batch(run_id, f"{run_id}-dup",
                    [{"id": "q1", "question": "a?"}, {"id": "q1", "question": "b?"}])), headers=H)
    check("Takroriy id -> 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
    r = client.post("/v1/rag/batch", content=json.dumps(batch(run_id, f"{run_id}-empty",
                    [{"id": "q1", "question": "   "}])), headers=H)
    check("Bo'sh question -> 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
    r = client.post("/v1/rag/batch", content=b"{not json", headers=H)
    check("Buzuq JSON -> 400", r.status_code == 400, str(r.status_code))

    # javobsiz savol (LLM chaqirilmaydi)
    r = client.post("/v1/rag/batch", content=json.dumps(batch(run_id, f"{run_id}-na", [QS[3]])), headers=H)
    na = r.json()["results"][0] if r.status_code == 200 else {}
    check("Javobsiz savol: no_answer=true, citations=[]", na.get("no_answer") is True and na.get("citations") == [],
          json.dumps(na, ensure_ascii=False)[:300])

    if not live_llm:
        return
    items = QS + [{"id": "q005", "question": "Bad language", "language": "xx"}]
    body = batch(run_id, f"{run_id}-b01", items)
    t0 = time.time()
    r = client.post("/v1/rag/batch", content=json.dumps(body, ensure_ascii=False).encode(), headers=H)
    dt = time.time() - t0
    check("POST /v1/rag/batch -> 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    d = r.json()
    res = d.get("results", [])
    check("Batch <= 120 s", dt <= 120, f"{dt:.1f}s")
    check("results soni = items soni, har id bir marta",
          sorted(x["id"] for x in res) == sorted(i["id"] for i in items), str([x["id"] for x in res]))
    check("system obyekti to'liq", all((d.get("system") or {}).get(k) for k in
                                       ("pipeline_version", "llm_model", "embedding_model", "index_version",
                                        "lex_snapshot_date")), json.dumps(d.get("system"), ensure_ascii=False))
    check("timing va summary bor", "total_ms" in d.get("timing", {}) and d.get("summary", {}).get("total") == len(items))
    by = {x["id"]: x for x in res}
    bad = by.get("q005", {})
    check("Bitta savol xatosi batch'ni yiqitmaydi (INVALID_LANGUAGE)",
          bad.get("status") == "error" and (bad.get("error") or {}).get("code") == "INVALID_LANGUAGE"
          and by.get("q001", {}).get("status") in ("ok", "no_answer"), json.dumps(bad, ensure_ascii=False)[:200])
    need = ("doc_id", "url", "article", "edition_date", "doc_status", "quote", "chunk_id")
    for qid in ("q001", "q002", "q003"):
        x = by.get(qid, {})
        cits, ctx = x.get("citations") or [], x.get("contexts") or []
        ctx_ids = {c["chunk_id"] for c in ctx}
        check(f"{qid}: status ok va citations bor", x.get("status") == "ok" and cits,
              f"{x.get('status')} {json.dumps(x.get('error'), ensure_ascii=False)}")
        check(f"{qid}: citations maydonlari to'liq", cits and all(all(c.get(k) for k in need) for c in cits),
              json.dumps(cits[:1], ensure_ascii=False)[:400])
        check(f"{qid}: citations[].chunk_id contexts ichida", all(c["chunk_id"] in ctx_ids for c in cits))
        check(f"{qid}: quote manba matnidan aynan olingan",
              all(c["quote"] in next(t["text"] for t in ctx if t["chunk_id"] == c["chunk_id"]) for c in cits))
        check(f"{qid}: contexts top-k, matn va ballar bilan",
              0 < len(ctx) and all("text" in c and c.get("retrieval_score") is not None and "rerank_score" in c
                                   for c in ctx))
        refs = {int(n) for n in __import__("re").findall(r"\[(\d+)\]", x.get("answer") or "")}
        check(f"{qid}: javobdagi [n] lar citations[].ref ga mos", refs == {c["ref"] for c in cits},
              f"{refs} vs {[c['ref'] for c in cits]}")
    check("o' / g' belgilari buzilmagan", "ʻ" in json.dumps(d, ensure_ascii=False) and "\\u" not in r.text,
          "")
    check("Rus savoliga rus tilida javob", by.get("q002", {}).get("answer_language") == "ru")
    check("Kirill savolga kirill javob", by.get("q003", {}).get("answer_language") == "uz-Cyrl")

    # idempotentlik
    t0 = time.time()
    r2 = client.post("/v1/rag/batch", content=json.dumps(body, ensure_ascii=False).encode(), headers=H)
    check("Bir xil batch_id -> saqlangan natija (qayta hisoblanmaydi)",
          r2.status_code == 200 and r2.json().get("timing") == d.get("timing") and time.time() - t0 < 3,
          f"{r2.status_code} {time.time() - t0:.1f}s")
    body2 = {**body, "items": body["items"][:2]}
    r3 = client.post("/v1/rag/batch", content=json.dumps(body2, ensure_ascii=False).encode(), headers=H)
    check("Shu batch_id boshqa mazmun bilan -> 409", r3.status_code == 409, str(r3.status_code))
    r4 = client.get(f"/v1/rag/batch/{body['batch_id']}", headers=H)
    check("GET /v1/rag/batch/{id} natijani qaytaradi", r4.status_code == 200 and r4.json().get("status") == "completed")
    r5 = client.get("/v1/rag/batch/yoq-batch", headers=H)
    check("Noma'lum batch_id -> 404", r5.status_code == 404, str(r5.status_code))

    # takrorlanuvchanlik: yangi batch_id, xuddi shu savollar -> bir xil manbalar
    body3 = batch(run_id, f"{run_id}-b02", QS[:3])
    r6 = client.post("/v1/rag/batch", content=json.dumps(body3, ensure_ascii=False).encode(), headers=H)
    same = all([c["chunk_id"] for c in by[q]["contexts"]] ==
               [c["chunk_id"] for c in {x["id"]: x for x in r6.json()["results"]}[q]["contexts"]] for q in ("q001", "q002", "q003"))
    check("Bir xil savol -> bir xil manbalar (contexts)", r6.status_code == 200 and same)

    # rate limit
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(30) as ex:  # parallel: tarmoq kechikishi bilan ketma-ket so'rov limitga yetmaydi
        rs = list(ex.map(lambda _: client.get("/v1/rag/batch/yoq", headers=H), range(40)))
    check("Rate limit: 429 + Retry-After",
          any(r.status_code == 429 and r.headers.get("retry-after") for r in rs), str({r.status_code for r in rs}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--key-env", default="RAG_TEST_KEY", help="API kalit shu muhit o'zgaruvchisida")
    ap.add_argument("--live-llm", action="store_true")
    a = ap.parse_args()
    if a.url:
        import httpx
        key = os.environ.get(a.key_env, "")
        if not key:
            sys.exit(f"{a.key_env} muhit o'zgaruvchisi bo'sh")
        with httpx.Client(base_url=a.url, timeout=180) as c:
            run(c, key, a.live_llm)
    else:
        from lexrag import config, llm
        tmp = Path(tempfile.mkdtemp(prefix="v1check-"))
        config.STATE = tmp  # sinov batch'lari haqiqiy data/state ga yozilmasin
        os.environ["RAG_API_KEYS"] = key = "test-" + uuid.uuid4().hex

        def fake_stream(system, user, temperature=0.1, max_tokens=8192, seed=None):
            llm.LAST.model, llm.LAST.usage = "mock", {"input_tokens": len(user) // 4, "output_tokens": 30}
            if "Mars" in user:  # haqiqiy LLM ham shunday javob beradi (promptdagi 4-qoida)
                txt = "Bazadagi hujjatlarda bu savolga aniq javob topilmadi. Yer kodeksiga qarang [1]."
            elif "RUS" in system:
                txt = "Согласно статье, срок составляет три года [1]. Подробности в [2]."
            else:
                txt = "Manbaga koʻra muddat belgilangan [1]. Qoʻshimcha shartlar ham bor [2][9]."
            for w in txt.split(" "):
                yield w + " "
            yield "\n<<<KEYINGI>>>\nSavol 1\nSavol 2\nSavol 3"
        llm.stream = fake_stream
        from fastapi.testclient import TestClient
        from lexrag.web import app as web
        with TestClient(web.app) as c:
            for _ in range(120):
                if web.STATE["ready"] or web.STATE["phase"] == "error":
                    break
                time.sleep(1)
            run(c, key, True)
    bad = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} o'tdi")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
