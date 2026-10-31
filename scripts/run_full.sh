#!/usr/bin/env bash
# To'liq pipeline: yuklash -> parse -> chunk -> tekshiruv -> hisobot -> vektor indeks.
# Har bosqich checkpoint bilan ishlaydi: to'xtab qolsa shu skriptni qayta ishga tushiring.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOG=data/state/full_run.log
mkdir -p data/state
step() { echo "=== $(date '+%F %T') $*" | tee -a "$LOG"; }

# Mac uxlab qolmasin (faqat skript ishlayotgan vaqtda)
command -v caffeinate >/dev/null && caffeinate -i -w $$ &

step "list";   $PY -m lexrag list   >>"$LOG" 2>&1
step "fetch";  $PY -m lexrag fetch  >>"$LOG" 2>&1
step "parse";  $PY -m lexrag parse  >>"$LOG" 2>&1
step "chunk";  $PY -m lexrag chunk  >>"$LOG" 2>&1
step "verify"; $PY -m lexrag verify --n 4 >>"$LOG" 2>&1
step "report"; $PY -m lexrag report >>"$LOG" 2>&1
step "index";  $PY -m lexrag index  >>"$LOG" 2>&1
step "report (yakuniy)"; $PY -m lexrag report >>"$LOG" 2>&1
step "TAYYOR"
