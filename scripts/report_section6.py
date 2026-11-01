"""report.md dagi faqat "## 6. Baholash" bo'limini yangilash (1-5 bo'limlar va baza sanasi o'zgarmaydi).

    .venv/bin/python scripts/report_section6.py

`python -m lexrag report` butun hisobotni qayta quradi (sana ham yangilanadi); bu skript faqat baholash qismini
eval/ fayllaridan qayta yozadi.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexrag.eval_report import report_section  # noqa: E402

p = ROOT / "report.md"
text = p.read_text(encoding="utf-8")
i = text.find("## 6. Baholash")
if i < 0:
    raise SystemExit("report.md da '## 6. Baholash' topilmadi")
j = text.find("\n## ", i + 5)
tail = text[j:] if j >= 0 else ""
p.write_text(text[:i] + report_section().rstrip() + "\n" + tail, encoding="utf-8")
print("->", p)
