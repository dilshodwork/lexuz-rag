"""Sinov serveri: asosiy serverga (8000) va uning bepul limit hisoblagichiga tegmasdan.

    .venv/bin/python scripts/test_server.py --port 8010 --free-limit 2 --dist /tmp/dalil-byok-dist

Kvota hisoblagichi vaqtinchalik faylda (--quota-db), frontend --dist papkasidan beriladi
(web/dist ni qayta yig'ish ishlab turgan asosiy serverning frontendini almashtirib yuboradi).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--free-limit", type=int, default=2)
    ap.add_argument("--global-limit", type=int, default=100)
    ap.add_argument("--dist", default=str(ROOT / "web" / "dist"))
    ap.add_argument("--quota-db", default="/tmp/dalil-test-quota.sqlite")
    ap.add_argument("--telegram-token", default="", help="sinov uchun soxta bot tokeni (initData HMAC tekshiruvi)")
    a = ap.parse_args()
    os.environ.update(FREE_DAILY_LIMIT=str(a.free_limit), GLOBAL_DAILY_LIMIT=str(a.global_limit),
                      DALIL_DIST=a.dist, DALIL_QUOTA_DB=a.quota_db)
    if a.telegram_token:
        os.environ["TELEGRAM_BOT_TOKEN"] = a.telegram_token
    sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run("lexrag.web.app:app", host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
