---
title: Dalil
emoji: ⚖️
colorFrom: red
colorTo: pink
sdk: docker
app_port: 7860
suggested_hardware: cpu-basic
startup_duration_timeout: 30m
pinned: false
license: mit
short_description: Oʻzbekiston qonunchiligi boʻyicha manbali savol-javob
---

# Dalil

Oʻzbekiston qonunchiligi boʻyicha savol-javob: har javob lex.uz Milliy bazasidagi aniq moddaga bogʻlanadi
([n] iqtiboslar, manba kartochkalari, ishonch tekshiruvi). Qidiruv: bge-m3 + BM25 gibrid (RRF).

* Baza: 1618 hujjat (qonunlar, kodekslar, Konstitutsiya), holat sanasi 31.10.2026. Manba: [lex.uz](https://lex.uz).
* Bu yuridik maslahat emas. Rasmiy davlat sayti emas.
* Bepul sinov: kuniga bir necha savol (server kaliti). Davom etish uchun "AI ulash" — oʻz Gemini / OpenAI /
  Claude kalitingiz (kalit faqat qurilmangizda saqlanadi).

Bu Space repo'si `scripts/hf_deploy.py` bilan avtomatik yigʻiladi — kodni shu yerda emas, asosiy loyihada oʻzgartiring.
Qidiruv indeksi alohida dataset repo'da (`HF_DATASET`), konteyner ishga tushganda yuklanadi.
