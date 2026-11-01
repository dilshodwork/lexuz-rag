"""Dalil'ni Hugging Face'ga chiqarish: (a) indeks -> dataset repo, (b) kod -> Space repo, (c) Space secrets.

Token: HF_TOKEN muhit o'zgaruvchisi yoki `hf auth login` keshi (huggingface_hub o'zi topadi). Token va kalitlar
hech qachon ekranga chiqarilmaydi: secrets lokal .env dan o'qiladi va to'g'ridan HfApi.add_space_secret ga beriladi.

    .venv/bin/python scripts/hf_deploy.py --dry-run              # hech narsa yuklanmaydi: reja, fayllar, hajmlar
    .venv/bin/python scripts/hf_deploy.py                        # hammasi: data + space + secrets
    .venv/bin/python scripts/hf_deploy.py --only space           # faqat kod (indeks o'zgarmagan bo'lsa)
    .venv/bin/python scripts/hf_deploy.py --only secrets
    .venv/bin/python scripts/hf_deploy.py --stage /tmp/dalil-space --stage-data /tmp/dalil-seed --dry-run
        # Space repo va dataset tarkibini lokal papkaga yig'ish (Docker'da lokal sinash uchun)

Nomlar: --space <user>/dalil, --dataset <user>/dalil-index (standart: token egasining nomi bilan).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPACE_TPL = ROOT / "deploy" / "hf-space"
DATA = ROOT / "data"

# Space repo tarkibi (manba: loyiha papkasi). web/dist va node_modules kirmaydi - Docker o'zi yig'adi.
SPACE_FILES = ["requirements-prod.txt", "report.md", "LICENSE"]
SPACE_DIRS = {"lexrag": None, "eval": None, "web": ["src", "public", "index.html", "package.json", "package-lock.json",
                                                    "tsconfig.json", "vite.config.ts"]}
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "node_modules", "dist", "*.tsbuildinfo")

# secrets (maxfiy, .env dan) va variables (ochiq sozlamalar)
SECRETS = ["GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "EVAL_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
VARIABLES_FROM_ENV = ["LLM_PROVIDER", "LLM_MODEL", "FREE_DAILY_LIMIT", "GLOBAL_DAILY_LIMIT",
                      "RATE_LIMIT_PER_MIN", "RATE_LIMIT_PER_DAY", "OPENAI_MODELS"]

# yuklanadigan fayllarda bo'lmasligi kerak bo'lgan narsalar (kalit tasodifan kodga tushib qolsa - to'xtaymiz)
LEAK = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{30,}|"
                  r"\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}\b")

DATASET_CARD = """---
license: other
license_name: lex-uz-public
pretty_name: Dalil qidiruv indeksi (lex.uz qonunlari)
language: [uz]
tags: [legal, uzbek, rag]
---

# Dalil qidiruv indeksi

lex.uz Milliy bazasidagi ochiq hujjatlar (qonunlar, kodekslar, Konstitutsiya; holat 31.10.2026) asosida
qurilgan qidiruv indeksi: `index/chroma` (ChromaDB, BAAI/bge-m3 vektorlari, moddalar bo'yicha chunklar),
`index/bm25` (BM25, o'zbek stemmeri), `metadata.csv` (hujjatlar ro'yxati).

Dalil Space'i ishga tushganda shu repo'dan yuklab oladi. Rasmiy matn: https://lex.uz. Bu yuridik maslahat emas.
"""


def say(*a):
    print(*a, flush=True)


def human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return str(n)


def read_env(path: Path) -> dict[str, str]:
    """.env ni o'qiydi (qiymatlar faqat xotirada, chop etilmaydi)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if v:
            out[k.strip()] = v
    return out


# ---------------------------------------------------------------- yig'ish
def stage_space(dest: Path) -> list[tuple[str, int]]:
    """Space repo tarkibini dest ga yig'adi. Qaytaradi: [(nisbiy yo'l, hajm)]."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for f in ("README.md", "Dockerfile", "start.sh"):
        shutil.copy2(SPACE_TPL / f, dest / f)
    (dest / ".dockerignore").write_text("**/node_modules\n**/dist\n**/__pycache__\n**/.DS_Store\n.env\ndata/\n",
                                        encoding="utf-8")
    for f in SPACE_FILES:
        shutil.copy2(ROOT / f, dest / f)
    for d, only in SPACE_DIRS.items():
        if only is None:
            shutil.copytree(ROOT / d, dest / d, ignore=SKIP)
            continue
        (dest / d).mkdir()
        for name in only:
            src = ROOT / d / name
            if src.is_dir():
                shutil.copytree(src, dest / d / name, ignore=SKIP)
            else:
                shutil.copy2(src, dest / d / name)
    return [(str(p.relative_to(dest)), p.stat().st_size) for p in sorted(dest.rglob("*")) if p.is_file()]


def leak_check(base: Path, files: list[str]) -> list[str]:
    bad = []
    for rel in files:
        p = base / rel
        if p.suffix in (".png", ".jpg", ".sqlite3", ".npy", ".bin") or p.stat().st_size > 5_000_000:
            continue
        try:
            if LEAK.search(p.read_text(encoding="utf-8", errors="ignore")):
                bad.append(rel)
        except OSError:
            pass
    return bad


def data_files() -> list[tuple[str, Path]]:
    """Dataset repo'ga yuklanadigan fayllar: (repo ichidagi yo'l, lokal fayl)."""
    out = []
    for sub in ("chroma", "bm25"):
        for p in sorted((DATA / "index" / sub).rglob("*")):
            if p.is_file() and p.name != ".DS_Store":
                out.append((f"index/{sub}/{p.relative_to(DATA / 'index' / sub)}", p))
    out.append(("metadata.csv", DATA / "metadata.csv"))
    return out


def stage_data(dest: Path) -> Path:
    """Indeksning izchil nusxasi: chroma.sqlite3 sqlite backup API bilan (8000-portdagi server ochib turgan bo'lsa ham
    yarim yozilgan holat tushmaydi), qolganlari oddiy nusxa."""
    if dest.exists():
        shutil.rmtree(dest)
    for rel, src in data_files():
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.name == "chroma.sqlite3":
            s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
            d = sqlite3.connect(out)
            with d:
                s.backup(d)
            s.close()
            d.close()
        else:
            shutil.copy2(src, out)
    (dest / "README.md").write_text(DATASET_CARD, encoding="utf-8")
    return dest


# ---------------------------------------------------------------- Hugging Face
def hf_api():
    from huggingface_hub import HfApi, get_token
    if not get_token():
        sys.exit("HF token topilmadi. Avval:  .venv/bin/hf auth login   (yoki HF_TOKEN muhit o'zgaruvchisi). "
                 "Tokenni chatga yubormang.")
    return HfApi()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="hech narsa yuklamaydi, faqat reja")
    ap.add_argument("--only", default="data,space,secrets", help="vergul bilan: data, space, secrets")
    ap.add_argument("--space", help="<user>/<nom> (standart <user>/dalil)")
    ap.add_argument("--dataset", help="<user>/<nom> (standart <user>/dalil-index)")
    ap.add_argument("--user", help="HF foydalanuvchi nomi (dry-run'da token bo'lmasa nomlar uchun)")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--stage", help="Space tarkibini shu papkaga yig'ish (standart: vaqtinchalik papka)")
    ap.add_argument("--stage-data", help="dataset tarkibini shu papkaga yig'ish (izchil nusxa; lokal Docker sinovi uchun)")
    ap.add_argument("--private-dataset", action="store_true", help="dataset private bo'lsin (Space'ga HF_TOKEN secret kerak bo'ladi)")
    a = ap.parse_args()
    parts = {p.strip() for p in a.only.split(",") if p.strip()}

    api = None
    user = a.user
    if not a.dry_run:
        api = hf_api()
        user = user or api.whoami()["name"]
    else:
        from huggingface_hub import get_token
        say(f"[dry-run] HF token: {'bor' if get_token() else 'yoʻq'} (qiymati koʻrsatilmaydi)")
    user = user or "<user>"
    space = a.space or f"{user}/dalil"
    dataset = a.dataset or f"{user}/dalil-index"
    say(f"Space:   {space}  ->  https://{space.replace('/', '-').lower()}.hf.space")
    say(f"Dataset: {dataset}")

    # ---- (a) indeks -> dataset
    if "data" in parts:
        files = data_files()
        missing = [rel for rel, p in files if not p.exists()]
        if missing:
            sys.exit(f"Indeks fayllari yo'q: {missing[:5]}")
        total = sum(p.stat().st_size for _, p in files)
        say(f"\n(a) Dataset: {len(files)} fayl, {human(total)}")
        for rel, p in files:
            if p.stat().st_size > 1_000_000:
                say(f"    {rel:<70} {human(p.stat().st_size):>9}")
        if a.stage_data:
            d = stage_data(Path(a.stage_data))
            say(f"    izchil nusxa: {d}")
        if not a.dry_run:
            with tempfile.TemporaryDirectory(prefix="dalil-data-") as tmp:
                d = stage_data(Path(tmp) / "data")
                api.create_repo(dataset, repo_type="dataset", private=a.private_dataset, exist_ok=True)
                api.upload_folder(repo_id=dataset, repo_type="dataset", folder_path=str(d),
                                  commit_message="Dalil indeksi", delete_patterns=["index/**"])
            say("    yuklandi")

    # ---- (b) kod -> Space
    if "space" in parts:
        dest = Path(a.stage) if a.stage else Path(tempfile.mkdtemp(prefix="dalil-space-"))
        listing = stage_space(dest)
        bad = leak_check(dest, [r for r, _ in listing])
        say(f"\n(b) Space: {len(listing)} fayl, {human(sum(s for _, s in listing))} -> {dest}")
        top: dict[str, int] = {}
        for rel, size in listing:
            k = rel.split("/")[0]
            top[k] = top.get(k, 0) + size
        for k, s in sorted(top.items()):
            say(f"    {k:<28} {human(s):>9}")
        if bad:
            sys.exit(f"TO'XTATILDI: kalitga o'xshash satr topildi: {bad}")
        say("    kalit tekshiruvi: toza")
        if not a.dry_run:
            api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
            api.upload_folder(repo_id=space, repo_type="space", folder_path=str(dest),
                              commit_message="Dalil: kod yangilandi",
                              delete_patterns=["lexrag/**", "web/**", "eval/**"])
            say("    yuklandi (Space build boshlanadi, ~10-15 daqiqa)")
        if not a.stage:
            shutil.rmtree(dest, ignore_errors=True)

    # ---- (c) secrets va variables
    if "secrets" in parts:
        env = read_env(Path(a.env_file))
        variables = {"ENV": "production", "HF_DATASET": dataset}
        variables.update({k: env[k] for k in VARIABLES_FROM_ENV if k in env})
        variables.setdefault("LLM_PROVIDER", "gemini")
        secrets = {k: env[k] for k in SECRETS if k in env}
        say(f"\n(c) Secrets ({a.env_file} dan, qiymatlar koʻrsatilmaydi):")
        for k in SECRETS:
            say(f"    {k:<22} {'oʻrnatiladi' if k in secrets else 'yoʻq (oʻtkazib yuboriladi)'}")
        # .env dan olinganlarining faqat nomi (qiymatlari ochiq sozlama bo'lsa ham ekranga chiqarilmaydi)
        say("    Variables: " + ", ".join(f"{k}={v}" if k in ("ENV", "HF_DATASET") or k not in env else k
                                          for k, v in variables.items()))
        if a.private_dataset:
            say("    Diqqat: dataset private - Space'ga HF_TOKEN (read) secret'ini qo'lda qo'shing")
        if not a.dry_run:
            for k, v in secrets.items():
                api.add_space_secret(space, k, v)
            for k, v in variables.items():
                api.add_space_variable(space, k, v)
            say("    oʻrnatildi (Space qayta ishga tushadi)")
        env.clear()
        secrets.clear()

    if a.dry_run:
        say("\n[dry-run] Hech narsa yuklanmadi.")


if __name__ == "__main__":
    main()
