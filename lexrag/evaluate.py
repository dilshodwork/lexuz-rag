"""Qidiruv sifatini baholash (LLM'siz): eval/questions.jsonl -> eval/results.json, eval/sweep.json, eval/results.md.

    python -m lexrag eval [--modes dense,bm25,hybrid,hybrid_plan] [--k 10] [--no-sweep]

Rejimlar (ilovadagi kod bilan aynan bir xil funksiyalar ishlatiladi):
  dense        bge-m3 + ChromaDB (cosine)
  bm25         BM25 (7 harfli o'zak)
  hybrid       ikkalasi, RRF: W_DENSE / (60 + rank) + W_BM25 / (60 + rank)  (retrieval.rrf)
  hybrid_plan  hybrid + murakkab savolni bo'lish (plan.split_question) va qismlarni RRF bilan birlashtirish (rag._fuse)

Metrikalar faqat javobi bazada bor savollarda: recall@k (gold moddalarning top-k da topilgan ulushi), hit@k,
MRR@10, nDCG@10 (binar, bitta moddaning bir nechta bo'lagi bir marta hisoblanadi). "Bazada yo'q" savollar uchun
rad etish: eng yaqin manba cosine < NO_ANSWER_COS bo'lsa LLM chaqirilmaydi (rag.prepare_steps bilan bir xil).

Dense va BM25 ro'yxatlari har savol uchun bir marta hisoblanadi; W_BM25 sweep shu ro'yxatlarni qayta birlashtiradi
(qo'shimcha qidiruvsiz), NO_ANSWER_COS sweep esa saqlangan eng yaqin cosine'larni turli chegaralar bilan solishtiradi.
"""
from __future__ import annotations

import contextlib
import json
import math
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import config, plan, rag
from .lang import detect_lang, script_of
from . import retrieval
from .retrieval import (MODEL, RRF_K, W_DENSE, bm25_search, candidates, chunk_meta, dense_search,
                        get_collection, rrf)

EVAL_DIR = config.ROOT / "eval"
QUESTIONS = EVAL_DIR / "questions.jsonl"
RESULTS = EVAL_DIR / "results.json"
SWEEP = EVAL_DIR / "sweep.json"
REPORT_MD = EVAL_DIR / "results.md"

MODES = ("dense", "bm25", "hybrid", "hybrid_plan")
MODE_NAMES = {"dense": "Dense (bge-m3)", "bm25": "BM25", "hybrid": "Gibrid (RRF)", "hybrid_plan": "Gibrid + bo'lish"}
N_EACH = 40          # hybrid_search standarti bilan bir xil
FILTERS = {"only_active": True, "no_amending": True, "doc_types": None}   # ilova standarti
W_GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0]
COS_GRID = [round(0.30 + 0.02 * i, 2) for i in range(21)]                # 0.30 .. 0.70
LANG_NAMES = {"uz": "lotin", "uz_cyr": "kirill", "ru": "rus"}


# ---------------------------------------------------------------- savollar
def load_questions(path: Path = QUESTIONS) -> list[dict]:
    """q["lang"] - savolning haqiqiy tili (to'plamdagi yorliq: kesimlar shu bo'yicha), q["lang_detected"] - ilova
    aniqlagan til (qidiruv shu bilan ishlaydi, xuddi ilovadagidek). Ular farq qilsa - til aniqlash xatosi.
    q["split"] - dev (sozlash) yoki test (yakuniy raqamlar)."""
    qs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            q["lang_detected"] = detect_lang(q["question"])
            q["lang"] = q.get("lang") or q["lang_detected"]
            q["script"] = script_of(q["question"])
            q["answerable"] = bool(q["gold"])
            q["split"] = q.get("split") or "dev"
            qs.append(q)
    return qs


def check_gold(qs: list[dict]) -> list[str]:
    """Har gold modda bazada bormi va standart filtrdan (amaldagi, o'zgartirish qonuni emas) o'tadimi."""
    col = get_collection(MODEL, create=False)
    errors = []
    for q in qs:
        for g in q["gold"]:
            got = col.get(where={"$and": [{"doc_id": g["doc_id"]}, {"article_number": g["article"]}]},
                          include=["metadatas"])
            if not got["ids"]:
                errors.append(f"{q['id']}: {g['doc_id']} {g['article']}-modda bazada yoʻq")
            elif not any(m.get("status") == "amalda" and not m.get("is_amending_law") for m in got["metadatas"]):
                errors.append(f"{q['id']}: {g['doc_id']} {g['article']}-modda standart filtrdan oʻtmaydi")
    return errors


# ---------------------------------------------------------------- metrikalar
def _key(meta: dict, cid: str) -> tuple[str, str]:
    m = meta.get(cid) or {}
    return str(m.get("doc_id") or cid.split("_", 1)[0]), str(m.get("article_number") or "")


def rank_metrics(ranking: list[str], meta: dict, gold: set, k_max: int = 10) -> dict:
    """ranking - chunk id lar tartibda. gold - {(doc_id, modda)}. Birinchi topilgan gold o'rni va metrikalar."""
    seen: set = set()
    gold_ranks: list[int] = []
    for i, cid in enumerate(ranking[:k_max], 1):
        key = _key(meta, cid)
        if key in gold and key not in seen:
            seen.add(key)
            gold_ranks.append(i)
    first = gold_ranks[0] if gold_ranks else None
    out = {"rank": first, "found": len(gold_ranks)}
    for k in range(1, k_max + 1):
        out[f"recall@{k}"] = sum(r <= k for r in gold_ranks) / len(gold)
        out[f"hit@{k}"] = float(first is not None and first <= k)
    out["mrr@10"] = 1 / first if first else 0.0
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), k_max) + 1))
    out["ndcg@10"] = sum(1 / math.log2(r + 1) for r in gold_ranks) / idcg
    return out


def _first_gold(lst: list[str], meta: dict, gold: set) -> int | None:
    for i, cid in enumerate(lst, 1):
        if _key(meta, cid) in gold:
            return i
    return None


def _mean(xs) -> float:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 1)


def summarize(per_q: list[dict], mode: str, k_max: int = 10) -> dict:
    ms = [q["modes"][mode]["metrics"] for q in per_q if q["answerable"]]
    out = {k: _mean(m[k] for m in ms) for k in [f"recall@{i}" for i in range(1, k_max + 1)]
           + [f"hit@{i}" for i in range(1, k_max + 1)] + ["mrr@10", "ndcg@10"]}
    out["recall_curve"] = [out[f"recall@{i}"] for i in range(1, k_max + 1)]
    out["n"] = len(ms)
    t = [q["modes"][mode]["ms"] for q in per_q]
    out.update(avg_ms=round(_mean(t), 1), p50_ms=_pct(t, .5), p95_ms=_pct(t, .95))
    return out


def rejection(per_q: list[dict], mode: str, thr: float) -> dict | None:
    rows = [(q["answerable"], q["modes"][mode].get("best_cos")) for q in per_q]
    if any(c is None for _, c in rows):
        return None
    neg = [c for a, c in rows if not a]
    pos = [c for a, c in rows if a]
    cr = sum(c < thr for c in neg)
    fr = sum(c < thr for c in pos)
    tpr = cr / len(neg) if neg else 0.0
    fpr = fr / len(pos) if pos else 0.0
    return {"threshold": thr, "n_none": len(neg), "correct_reject": cr, "n_answerable": len(pos), "false_reject": fr,
            "reject_rate": round(tpr, 4), "false_reject_rate": round(fpr, 4),
            "accuracy": round((cr + len(pos) - fr) / len(rows), 4),
            "balanced_accuracy": round((tpr + (1 - fpr)) / 2, 4)}


# ---------------------------------------------------------------- qidiruv
def _raw(question: str, lang: str) -> dict:
    """Bitta so'rov: dense va BM25 ro'yxatlari (N_EACH ta) + vaqtlar. Ilovadagi retrieval.candidates aynan shu."""
    t0 = time.perf_counter()
    tm: dict = {}
    c = candidates(question, lang, N_EACH, **FILTERS, timing=tm)
    total = (time.perf_counter() - t0) * 1000
    ms_bm25 = tm.get("bm25", 0.0)
    return {"dense": c["dense"], "cos": c["cos"], "lex": c["lex"], "w_bm25": c["w_bm25"], "w_factor": c["w_factor"],
            "ms_dense": total - ms_bm25, "ms_bm25": ms_bm25}


def _hybrid(raw: dict, w_bm25: float | None = None) -> tuple[list[str], dict, float]:
    """w_bm25 - asosiy og'irlik (sweep); berilmasa joriy W_BM25 bilan hisoblangan og'irlik."""
    t0 = time.perf_counter()
    w = raw["w_bm25"] if w_bm25 is None else w_bm25 * raw["w_factor"]
    fused = rrf([(raw["dense"], W_DENSE), (raw["lex"], w)], RRF_K)
    ranking = sorted(fused, key=fused.get, reverse=True)
    return ranking, fused, (time.perf_counter() - t0) * 1000


def _best_cos(ranking: list[str], cos: dict, k: int = rag.K_CONTEXT) -> float:
    """rag.prepare_steps bilan bir xil: LLM'ga beriladigan k ta manbaning eng yuqori cosine'i."""
    return round(max((cos.get(c) or 0) for c in ranking[:k]) if ranking else 0.0, 4)


def _top(ranking: list[str], meta: dict, gold: set, raw: dict, n: int = 5) -> list[dict]:
    out = []
    for i, cid in enumerate(ranking[:n], 1):
        m = meta.get(cid) or {}
        out.append({"rank": i, "chunk_id": cid, "doc": rag.short_doc(m.get("doc_title", "")),
                    "art": m.get("article_number") or "", "title": (m.get("article_title") or "")[:80],
                    "gold": _key(meta, cid) in gold, "cos": raw["cos"].get(cid),
                    "rank_dense": raw["dense"].index(cid) + 1 if cid in raw["dense"] else None,
                    "rank_bm25": raw["lex"].index(cid) + 1 if cid in raw["lex"] else None})
    return out


def eval_question(q: dict, modes: tuple[str, ...], k_max: int, lock=None) -> tuple[dict, dict]:
    """(savol natijasi, sweep uchun xom ma'lumot)."""
    lock = lock or contextlib.nullcontext()
    gold = {(g["doc_id"], g["article"]) for g in q["gold"]}
    with lock:
        raw = _raw(q["question"], q["lang_detected"])
        parts = plan.split_question(q["question"]) if "hybrid_plan" in modes else []
        sub = [(p, _raw(p, q["lang_detected"])) for p in parts]
        ids = raw["dense"] + raw["lex"] + [c for _, r in sub for c in r["dense"] + r["lex"]]
        meta = chunk_meta(ids)
    res = {k: q[k] for k in ("id", "question", "category", "difficulty", "lang", "lang_detected", "script",
                             "answerable", "split")}
    res["gold"] = q["gold"]
    res["parts"] = parts
    res["gold_rank_dense"] = _first_gold(raw["dense"], meta, gold) if gold else None
    res["gold_rank_bm25"] = _first_gold(raw["lex"], meta, gold) if gold else None
    res["modes"] = {}
    hyb, _, ms_rrf = _hybrid(raw)
    for mode in modes:
        if mode == "dense":
            ranking, ms, best = raw["dense"], raw["ms_dense"], _best_cos(raw["dense"], raw["cos"])
        elif mode == "bm25":
            ranking, ms, best = raw["lex"], raw["ms_bm25"], None
        elif mode == "hybrid":
            ranking, ms, best = hyb, raw["ms_dense"] + raw["ms_bm25"] + ms_rrf, _best_cos(hyb, raw["cos"])
        else:  # hybrid_plan: ilovadagi kabi har qidiruvdan K_CONTEXT ta, keyin rag._fuse
            ms = raw["ms_dense"] + raw["ms_bm25"] + ms_rrf
            if not sub:
                ranking, best = hyb, _best_cos(hyb, raw["cos"])
            else:
                lists, cos_all = [], dict(raw["cos"])
                for r in [raw] + [r for _, r in sub]:
                    rk, _, m2 = _hybrid(r)
                    if r is not raw:
                        ms += r["ms_dense"] + r["ms_bm25"] + m2
                    cos_all.update({c: v for c, v in r["cos"].items() if c not in cos_all})
                    lists.append([{"chunk_id": c, "cosine": r["cos"].get(c)} for c in rk[:rag.K_CONTEXT]])
                t0 = time.perf_counter()
                ranking = [h["chunk_id"] for h in rag._fuse(lists, max(rag.K_CONTEXT, rag.K_SPLIT))]
                ms += (time.perf_counter() - t0) * 1000
                best = round(max((cos_all.get(c) or 0) for c in ranking) if ranking else 0.0, 4)
        entry = {"ms": round(ms, 1), "best_cos": best, "top": _top(ranking, meta, gold, raw)}
        if gold:
            entry["metrics"] = {k: round(v, 4) if isinstance(v, float) else v
                                for k, v in rank_metrics(ranking, meta, gold, k_max).items()}
        res["modes"][mode] = entry
    sweep_raw = {"raw": raw, "meta": meta, "gold": gold}
    return res, sweep_raw


# ---------------------------------------------------------------- sweep
def _w_grid(per_q: list[dict], raws: list[dict], k_max: int) -> list[dict]:
    rows = []
    for w in W_GRID:
        ms = []
        for q, r in zip(per_q, raws):
            if not q["answerable"]:
                continue
            ranking, _, _ = _hybrid(r["raw"], w)
            ms.append(rank_metrics(ranking, r["meta"], r["gold"], k_max))
        rows.append({"w_bm25": w, "recall@1": _mean(m["recall@1"] for m in ms),
                     "recall@5": _mean(m["recall@5"] for m in ms), "recall@10": _mean(m["recall@10"] for m in ms),
                     "mrr@10": _mean(m["mrr@10"] for m in ms), "ndcg@10": _mean(m["ndcg@10"] for m in ms)})
    return rows


def _cos_info(per_q: list[dict]) -> dict:
    pos = sorted(q["modes"]["hybrid"]["best_cos"] for q in per_q if q["answerable"])
    neg = sorted(q["modes"]["hybrid"]["best_cos"] for q in per_q if not q["answerable"])
    return {"answerable_cos": {"min": pos[0] if pos else None, "p10": _pct(pos, .1) if pos else None,
                               "median": statistics.median(pos) if pos else None},
            "none_cos": neg, "separable": bool(pos and neg and max(neg) < pos[0])}


SELECT_SPLIT = "dev"   # sozlash (eng yaxshi qiymatni tanlash) faqat shu qismda; test - faqat hisobot uchun


def sweep(per_q: list[dict], raws: list[dict], k_max: int = 10) -> dict:
    """W_BM25 va NO_ANSWER_COS sweep. Har qism (dev, test, hammasi) uchun jadval hisoblanadi, lekin "best" faqat
    DEV bo'yicha tanlanadi (test'ga moslab sozlanmasin). "grid" - dev jadvali (veb-sahifa uni chizadi)."""
    groups = {"all": list(range(len(per_q)))}
    for i, q in enumerate(per_q):
        groups.setdefault(q.get("split") or "dev", []).append(i)
    sel = SELECT_SPLIT if SELECT_SPLIT in groups else "all"
    w_by, c_by, info_by = {}, {}, {}
    for g, idx in groups.items():
        pq, rw = [per_q[i] for i in idx], [raws[i] for i in idx]
        w_by[g] = _w_grid(pq, rw, k_max)
        c_by[g] = [rejection(pq, "hybrid", t) for t in COS_GRID]
        info_by[g] = _cos_info(pq)
    # asosiy metrika - recall@5 (LLM'ga boradigan manbalar orasida to'g'ri modda bormi), teng bo'lsa MRR@10
    best_w = max(w_by[sel], key=lambda r: (r["recall@5"], r["mrr@10"], -abs(r["w_bm25"] - retrieval.W_BM25)))
    best_c = max(c_by[sel], key=lambda r: (r["balanced_accuracy"], -r["false_reject"], -abs(r["threshold"] - rag.NO_ANSWER_COS)))
    return {
        "selected_on": sel,
        "w_bm25": {"current": retrieval.W_BM25, "grid": w_by[sel], "grid_by_split": w_by, "best": best_w,
                   "note": ("Ruscha savollarda BM25 ishlatilmaydi (RU_BM25 = off: baza oʻzbekcha)." if retrieval.RU_BM25 == "off"
                            else "Ruscha savollarda BM25 ogʻirligi W_BM25 × 0.75 (lugʻat atamasi bor) yoki × 0.25.")},
        "no_answer_cos": {"current": rag.NO_ANSWER_COS, "grid": c_by[sel], "grid_by_split": c_by, "best": best_c,
                          **info_by[sel], "by_split": info_by},
    }


# ---------------------------------------------------------------- yig'ish
def _git() -> dict:
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True, text=True, timeout=5)
        d = subprocess.run(["git", "status", "--porcelain", "--", "lexrag"], cwd=config.ROOT, capture_output=True, text=True, timeout=5)
        return {"commit": h.stdout.strip() or None, "dirty": bool(d.stdout.strip())}
    except Exception:  # noqa: BLE001
        return {"commit": None, "dirty": None}


def _slices(per_q: list[dict], modes, field: str) -> dict:
    out: dict = {}
    for q in per_q:
        if q["answerable"]:
            out.setdefault(q[field], []).append(q)
    return {v: {m: {"n": len(qs), "recall@5": _mean(q["modes"][m]["metrics"]["recall@5"] for q in qs),
                    "mrr@10": _mean(q["modes"][m]["metrics"]["mrr@10"] for q in qs),
                    "hit@1": _mean(q["modes"][m]["metrics"]["hit@1"] for q in qs)} for m in modes}
            for v, qs in sorted(out.items(), key=lambda kv: -len(kv[1]))}


def run(modes: tuple[str, ...] = MODES, k_max: int = 10, do_sweep: bool = True, write: bool = True,
        progress: Callable[[int, int, str], None] | None = None, lock=None) -> dict:
    t_start = time.time()
    qs = load_questions()
    errors = check_gold(qs)
    if errors:
        raise ValueError("Gold moddalar xato:\n" + "\n".join(errors))
    with lock or contextlib.nullcontext():
        dense_search("isitish", 1, **FILTERS)   # model va indeks xotiraga (vaqt o'lchoviga kirmasin)
        bm25_search("isitish", 1, **FILTERS)
    per_q, raws = [], []
    for i, q in enumerate(qs):
        if progress:
            progress(i, len(qs), q["question"])
        r, raw = eval_question(q, modes, k_max, lock)
        per_q.append(r)
        raws.append(raw)
    if progress:
        progress(len(qs), len(qs), "")
    summary = {m: summarize(per_q, m, k_max) for m in modes}
    rej = {m: rejection(per_q, m, rag.NO_ANSWER_COS) for m in modes}
    by_split = {}
    for s in sorted({q["split"] for q in per_q}):
        pq = [q for q in per_q if q["split"] == s]
        by_split[s] = {"n_questions": len(pq), "n_answerable": sum(q["answerable"] for q in pq),
                       "n_none": sum(not q["answerable"] for q in pq),
                       "counts": {f: _count(pq, f) for f in ("lang", "category", "difficulty")},
                       "summary": {m: summarize(pq, m, k_max) for m in modes},
                       "rejection": {m: rejection(pq, m, rag.NO_ANSWER_COS) for m in modes},
                       "slices": {f: _slices(pq, modes, f) for f in ("category", "lang", "difficulty")}}
    lang_err = [{"id": q["id"], "lang": q["lang"], "detected": q["lang_detected"]} for q in per_q
                if q["lang"] != q["lang_detected"]]
    results = {
        "meta": {"created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), **_git(),
                 "n_questions": len(qs), "n_answerable": sum(q["answerable"] for q in qs),
                 "n_none": sum(not q["answerable"] for q in qs), "k": k_max, "modes": list(modes),
                 "mode_names": {m: MODE_NAMES[m] for m in modes},
                 "params": {"embedding": MODEL, "W_DENSE": W_DENSE, "W_BM25": retrieval.W_BM25, "RRF_K": RRF_K, "N_EACH": N_EACH,
                            "NO_ANSWER_COS": rag.NO_ANSWER_COS, "K_CONTEXT": rag.K_CONTEXT, "K_SPLIT": rag.K_SPLIT,
                            "filters": FILTERS},
                 "counts": {"lang": _count(qs, "lang"), "category": _count(qs, "category"),
                            "difficulty": _count(qs, "difficulty"), "split": _count(qs, "split")},
                 "lang_detect_errors": lang_err,
                 "elapsed_s": None},
        "summary": summary,
        "rejection": rej,
        "slices": {f: _slices(per_q, modes, f) for f in ("category", "lang", "difficulty")},
        "by_split": by_split,
        "questions": per_q,
    }
    sw = sweep(per_q, raws, k_max) if do_sweep and "hybrid" in modes else None
    if sw:
        sw["meta"] = {"created": results["meta"]["created"], "commit": results["meta"]["commit"]}
    results["meta"]["elapsed_s"] = round(time.time() - t_start, 1)
    if write:
        EVAL_DIR.mkdir(exist_ok=True)
        # ixcham (veb-sahifa uni to'liq yuklaydi); o'qish uchun - eval/results.md
        RESULTS.write_text(json.dumps(results, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if sw:
            SWEEP.write_text(json.dumps(sw, ensure_ascii=False, indent=1), encoding="utf-8")
        REPORT_MD.write_text(markdown(results, sw), encoding="utf-8")
    return {"results": results, "sweep": sw}


def _count(qs, field) -> dict:
    out: dict = {}
    for q in qs:
        out[q[field]] = out.get(q[field], 0) + 1
    return out


# ---------------------------------------------------------------- hisobot
def _p(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def markdown(r: dict, sw: dict | None) -> str:
    m = r["meta"]
    p = m["params"]
    modes = m["modes"]
    L = [f"# Qidiruv sifatini baholash", "",
         f"Yaratilgan: {m['created']} · commit `{m['commit']}`{' (lexrag/ da commit qilinmagan o‘zgarish bor)' if m['dirty'] else ''}"
         f" · {m['elapsed_s']} s", "",
         f"Savollar: {m['n_questions']} ta ({m['n_answerable']} tasining javobi bazada bor, {m['n_none']} tasi bazada yo'q). "
         f"Til: " + ", ".join(f"{LANG_NAMES.get(k, k)} {v}" for k, v in m["counts"]["lang"].items()) + ". "
         f"Sozlamalar: W_DENSE={p['W_DENSE']}, W_BM25={p['W_BM25']}, RRF_K={p['RRF_K']}, har usuldan {p['N_EACH']} ta nomzod, "
         f"NO_ANSWER_COS={p['NO_ANSWER_COS']}, filtr: faqat amaldagi, o'zgartirish qonunlarisiz. LLM chaqirilmagan.", "",
         "## Asosiy natija", "",
         "| Rejim | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | o'rtacha vaqt |", "|---|---|---|---|---|---|---|---|"]
    for mo in modes:
        s = r["summary"][mo]
        L.append(f"| {MODE_NAMES[mo]} | {_p(s['recall@1'])} | {_p(s['recall@3'])} | {_p(s['recall@5'])} | {_p(s['recall@10'])} "
                 f"| {s['mrr@10']:.3f} | {s['ndcg@10']:.3f} | {s['avg_ms']:.0f} ms |")
    L += ["", "## \"Bazada yo'q\" savollarni rad etish", "",
          f"Chegara NO_ANSWER_COS = {p['NO_ANSWER_COS']} (LLM'ga beriladigan {p['K_CONTEXT']} ta manbaning eng yuqori cosine'i shundan past bo'lsa — \"topilmadi\").", "",
          "| Rejim | to'g'ri rad etildi | noto'g'ri rad etildi (javobi bor savol) | aniqlik |", "|---|---|---|---|"]
    for mo in modes:
        x = r["rejection"][mo]
        if x:
            L.append(f"| {MODE_NAMES[mo]} | {x['correct_reject']}/{x['n_none']} | {x['false_reject']}/{x['n_answerable']} | {_p(x['accuracy'])} |")
        else:
            L.append(f"| {MODE_NAMES[mo]} | — (cosine yo'q) | — | — |")
    for f, title in (("category", "Kategoriya"), ("lang", "Til / yozuv"), ("difficulty", "Qiyinlik")):
        L += ["", f"## {title} bo'yicha recall@5", "", f"| {title} | n | " + " | ".join(MODE_NAMES[mo] for mo in modes) + " |",
              "|---|---|" + "---|" * len(modes)]
        for v, row in r["slices"][f].items():
            n = next(iter(row.values()))["n"]
            L.append(f"| {LANG_NAMES.get(v, v) if f == 'lang' else v} | {n} | " + " | ".join(_p(row[mo]["recall@5"]) for mo in modes) + " |")
    if sw:
        w = sw["w_bm25"]
        L += ["", "## Sweep: W_BM25 (gibrid)", "", "| W_BM25 | R@1 | R@5 | MRR@10 | nDCG@10 |", "|---|---|---|---|---|"]
        for row in w["grid"]:
            mark = " (joriy)" if row["w_bm25"] == w["current"] else ""
            L.append(f"| {row['w_bm25']}{mark} | {_p(row['recall@1'])} | {_p(row['recall@5'])} | {row['mrr@10']:.3f} | {row['ndcg@10']:.3f} |")
        L.append(f"\nEng yaxshi (recall@5, teng bo'lsa MRR@10 bo'yicha): W_BM25 = {w['best']['w_bm25']}. {w['note']}")
        c = sw["no_answer_cos"]
        L += ["", "## Sweep: NO_ANSWER_COS", "", "| chegara | to'g'ri rad | noto'g'ri rad | balanslangan aniqlik |", "|---|---|---|---|"]
        for row in c["grid"]:
            if round(row["threshold"] * 100) % 4 == 2 or abs(row["threshold"] - c["current"]) < 1e-9:
                mark = " (joriy)" if abs(row["threshold"] - c["current"]) < 1e-9 else ""
                L.append(f"| {row['threshold']:.2f}{mark} | {row['correct_reject']}/{row['n_none']} | {row['false_reject']}/{row['n_answerable']} | {_p(row['balanced_accuracy'])} |")
        a = c["answerable_cos"]
        L.append(f"\nJavobi bor savollarda eng yaqin cosine: min {a['min']}, 10-persentil {a['p10']}, mediana {a['median']}. "
                 f"Bazada yo'q savollarda: {', '.join(str(x) for x in c['none_cos'])}. "
                 + ("Ikki guruh to'liq ajraladi." if c["separable"] else "Ikki guruh to'liq ajralmaydi."))
    L += ["", "## Xatolar (gibrid: gold modda top-5 da yo'q)", "", "| id | savol | gold | gibrid o'rni | dense o'rni | BM25 o'rni |", "|---|---|---|---|---|---|"]
    for q in r["questions"]:
        if not q["answerable"] or "hybrid" not in q["modes"]:
            continue
        rk = q["modes"]["hybrid"]["metrics"]["rank"]
        if rk is None or rk > 5:
            g = "; ".join(f"{x['doc']} {x['article']}-m." for x in q["gold"])
            L.append(f"| {q['id']} | {q['question']} | {g} | {rk or '>10'} | {q['gold_rank_dense'] or '>40'} | {q['gold_rank_bm25'] or '>40'} |")
    return "\n".join(L) + "\n"


def report_section() -> str:
    """report.md uchun "6. Baholash" bo'limi (eval/results.json, sweep.json, baseline_w06.json, answers.json dan)."""
    def load(p):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    r, sw = load(RESULTS), load(SWEEP)
    base, ans = load(EVAL_DIR / "baseline_w06.json"), load(EVAL_DIR / "answers.json")
    if not r:
        return ""
    m, S, p = r["meta"], r["summary"], r["meta"]["params"]
    L = ["## 6. Baholash (qidiruv sifati)", "",
         f"To'plam: `eval/questions.jsonl`, {m['n_questions']} savol — {m['n_answerable']} tasi gold modda bilan, {m['n_none']} tasi "
         "bazada yo'q; " + ", ".join(f"{LANG_NAMES.get(k, k)} {v}" for k, v in m["counts"]["lang"].items()) + ". "
         "Savollar modda matnini o'qib, oddiy odam tilida parafraza qilib yozilgan; gold modda bazada borligi har safar "
         f"tekshiriladi. LLM'siz. Commit `{m['commit']}`, {m['created'][:16].replace('T', ' ')}. Metodika: `eval/README.md`.", "",
         "| Rejim | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | vaqt |", "|---|---|---|---|---|---|---|---|"]
    for mo in m["modes"]:
        s = S[mo]
        L.append(f"| {MODE_NAMES[mo]} | {_p(s['recall@1'])} | {_p(s['recall@3'])} | {_p(s['recall@5'])} | {_p(s['recall@10'])} "
                 f"| {s['mrr@10']:.3f} | {s['ndcg@10']:.3f} | {s['avg_ms']:.0f} ms |")
    rej = r["rejection"].get("hybrid")
    if rej:
        L += ["", f"\"Bazada yo'q\" savollarni rad etish (NO_ANSWER_COS = {p['NO_ANSWER_COS']}): {rej['correct_reject']}/{rej['n_none']} "
                  f"to'g'ri rad, javobi bor savollardan {rej['false_reject']}/{rej['n_answerable']} xato rad, aniqlik {_p(rej['accuracy'])}."]
    if base and sw:
        b = base["summary"]["hybrid"]
        L += ["", "Standartlar sweep bo'yicha o'zgardi:", "",
              "| | oldin (W_BM25 0.6, NO_ANSWER_COS 0.45) | keyin |", "|---|---|---|",
              f"| Gibrid recall@5 | {_p(b['recall@5'])} | {_p(S['hybrid']['recall@5'])} |",
              f"| Gibrid recall@1 | {_p(b['recall@1'])} | {_p(S['hybrid']['recall@1'])} |",
              f"| Gibrid MRR@10 | {b['mrr@10']:.3f} | {S['hybrid']['mrr@10']:.3f} |", ""]
        L.append(f"W_BM25 = {p['W_BM25']}: BM25 parafrazali savollarda umumiy so'zlar bo'yicha shovqin beradi va RRF'da dense topgan "
                 f"moddani pastga suradi (BM25 yolg'iz recall@5 {_p(S['bm25']['recall@5'])}). Sof dense (W_BM25 = 0) MRR'da biroz "
                 f"yaxshiroq ({S['dense']['mrr@10']:.3f}), lekin recall@5 pastroq ({_p(S['dense']['recall@5'])}). NO_ANSWER_COS: javobi bor "
                 f"savollarda eng yaqin cosine ≥ {sw['no_answer_cos']['answerable_cos']['min']}, \"yo'q\" savollarda "
                 f"{', '.join(str(x) for x in sw['no_answer_cos']['none_cos'])} — 0.46–0.54 oralig'i bir xil natija beradi, 0.48 tanlandi.")
    if ans:
        a = ans["summary"]
        L += ["", f"Javob sifati (ixtiyoriy, {a['answered']} savol, {ans['meta']['model']}, {ans['meta']['llm_requests']} ta LLM so'rovi): "
                  f"faithfulness (ishonch tekshiruvi tasdiqlagan da'volar ulushi) {_p(a['faithfulness'])}, gold modda iqtibos qilingan "
                  f"{a['gold_cited']}/{a['answered']}, [n] lar to'g'ri {a['cites_valid']}/{a['answered']}. Ruscha javobda tekshiruv "
                  "ma'no o'xshashligini past baholaydi (manba o'zbekcha) — r01 javobi to'g'ri, lekin \"past\" chiqdi."]
    L += ["", "Xulosa: asosiy ishni dense (bge-m3) qiladi; BM25 bu to'plamda yordamchi xolos. Eng ko'p xato: savol kundalik so'z "
              "bilan, modda esa rasmiy atama bilan yozilgan holatlar (\"o'g'irlik\" o'rniga \"yashirincha olib qo'yish\", \"QQS\" "
              "o'rniga \"налог на добавленную стоимость\"). Kirill savollarda recall pastroq. To'liq jadvallar: `eval/results.md`, "
              "veb-ilovada `/baholash`.", ""]
    return "\n".join(L)


def cli(modes: str | None = None, k: int = 10, do_sweep: bool = True):
    ms = tuple(x.strip() for x in (modes or ",".join(MODES)).split(",") if x.strip())
    bad = [x for x in ms if x not in MODES]
    if bad:
        raise SystemExit(f"Nomaʼlum rejim: {bad}. Mumkin: {', '.join(MODES)}")

    def prog(i, n, q):
        print(f"\r[{i}/{n}] {q[:70]:<70}", end="", flush=True)
    out = run(ms, k, do_sweep, progress=prog)
    print()
    r = out["results"]
    print(markdown(r, out["sweep"]).split("## Kategoriya")[0])
    print(f"Yozildi: {RESULTS.relative_to(config.ROOT)}, {REPORT_MD.relative_to(config.ROOT)}"
          + (f", {SWEEP.relative_to(config.ROOT)}" if out["sweep"] else ""))
