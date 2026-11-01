#!/bin/sh
# Konteyner start: ma'lumotlar papkasini tanlaydi va uvicorn'ni ishga tushiradi.
# Indeks va model fonda yuklanadi (lexrag/web/app.py), port darhol ochiladi - /api/health "loading" qaytaradi.
set -e

# HF persistent storage (pullik) ulangan bo'lsa /data saqlanib qoladi: indeks qayta yuklanmaydi, bepul limit
# hisoblagichi o'chmaydi. Bepul tarifda /data yo'q - /tmp (Space qayta ishga tushganda tozalanadi).
if [ -z "$DALIL_DATA_DIR" ]; then
  if [ -d /data ] && [ -w /data ]; then DALIL_DATA_DIR=/data/dalil; else DALIL_DATA_DIR=/tmp/dalil; fi
fi
export DALIL_DATA_DIR
mkdir -p "$DALIL_DATA_DIR/state"
export DALIL_QUOTA_DB="${DALIL_QUOTA_DB:-$DALIL_DATA_DIR/state/quota.sqlite}"
echo "Dalil: data=$DALIL_DATA_DIR quota=$DALIL_QUOTA_DB dataset=${HF_DATASET:-none} port=${PORT:-7860}"

# bitta worker: bepul limit, rate limit va qidiruv qulfi bitta jarayon xotirasida
exec python -m uvicorn lexrag.web.app:app --host 0.0.0.0 --port "${PORT:-7860}" --workers 1 \
  --no-server-header --timeout-keep-alive 30 --log-level info
