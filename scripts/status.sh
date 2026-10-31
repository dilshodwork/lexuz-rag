#!/usr/bin/env bash
# Pipeline holatini jonli ko'rsatadi (har 5 soniyada yangilanadi). To'xtatish: Ctrl + C.
# Faqat log faylni o'qiydi: jarayonga ta'sir qilmaydi va AI token sarflamaydi.
cd "$(dirname "$0")/.."
LOG=data/state/full_run.log

while true; do
  # faqat oxirgi ishga tushirishdagi qatorlar
  start=$(grep -n "=== .* list$" "$LOG" | tail -1 | cut -d: -f1)
  run=$(tail -n +"${start:-1}" "$LOG")
  last_bar=$(tail -c 400 "$LOG" | tr '\r' '\n' | grep -v '^$' | tail -1)
  pct=$(echo "$last_bar" | grep -oE '^[^:]+: +[0-9]+%' | grep -oE '[0-9]+%' | head -1)
  eta=$(echo "$last_bar" | grep -oE '<[0-9:]+' | tr -d '<' | head -1)

  clear
  current=""
  echo "lex.uz RAG pipeline holati    $(date '+%H:%M:%S')"
  echo "-----------------------------------------------------------"
  i=0
  for s in list fetch parse chunk verify report index "report (yakuniy)" TAYYOR; do
    i=$((i + 1))
    case $s in
      list)   name="Ro'yxatni yig'ish";;
      fetch)  name="Hujjatlarni yuklash (1616)";;
      parse)  name="Tozalash va metadata";;
      chunk)  name="Chunklarga bo'lish";;
      verify) name="Saytdagi matn bilan solishtirish";;
      report) name="Hisobot (report.md)";;
      index)  name="Embedding + ChromaDB (eng uzun)";;
      "report (yakuniy)") name="Yakuniy hisobot";;
      TAYYOR) name="RAG baza tayyor";;
    esac
    if echo "$run" | grep -q "=== .* ${s}$"; then
      # keyingi bosqich boshlangan bo'lsa - bu bosqich tugagan
      next_started=$(echo "$run" | grep "^===" | grep -A1 "=== .* ${s}$" | tail -1 | grep -v "=== .* ${s}$")
      if [ -n "$next_started" ] || [ "$s" = "TAYYOR" ]; then
        printf "  [x] %d. %s\n" $i "$name"
      else
        printf "  [>] %d. %s   %s  (qolgan vaqt: %s)\n" $i "$name" "${pct:-...}" "${eta:-...}"
        current="$name"
      fi
    else
      printf "  [ ] %d. %s\n" $i "$name"
    fi
  done
  echo "-----------------------------------------------------------"
  if echo "$run" | grep -q "=== .* TAYYOR$"; then
    echo "Hammasi tugadi. Natija: report.md"
    break
  fi
  if ! pgrep -f "run_full.sh" >/dev/null; then
    echo "DIQQAT: pipeline ishlamayapti (to'xtagan yoki xato bilan chiqqan)."
    echo "Davom ettirish:  bash scripts/run_full.sh"
    echo "Oxirgi xato:     tail -20 $LOG"
  fi
  echo "Joriy bosqich: ${current:-...}"
  if [ "$current" = "Embedding + ChromaDB (eng uzun)" ]; then
    echo "Eslatma: chunklar qisqasidan uzuniga qarab hisoblanadi, shuning uchun 'qolgan vaqt'"
    echo "boshida kam ko'rinadi. Haqiqiy taxmin: jami ~11 soat."
  fi
  echo "Chiqish: Ctrl + C (jarayon to'xtamaydi)"
  sleep 5
done
