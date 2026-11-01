"""eval/results.md ni saqlangan eval/results.json + sweep.json dan qayta yozish (qidiruvni qayta ishga tushirmasdan).

    .venv/bin/python scripts/eval_markdown.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag import evaluate as E  # noqa: E402

r = json.loads(E.RESULTS.read_text(encoding="utf-8"))
sw = json.loads(E.SWEEP.read_text(encoding="utf-8")) if E.SWEEP.exists() else None
E.REPORT_MD.write_text(E.markdown(r, sw), encoding="utf-8")
print("->", E.REPORT_MD)
