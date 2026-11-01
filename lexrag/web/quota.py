"""Bepul sinov limiti: server kaliti bilan kuniga N ta savol (o'z AI kaliti yo'q foydalanuvchilar uchun).

Sozlash .env da:
    FREE_DAILY_LIMIT=5        # bitta foydalanuvchiga kuniga
    GLOBAL_DAILY_LIMIT=100    # hammaga birgalikda kuniga (server kalitini himoyalash)
    TELEGRAM_BOT_TOKEN=       # ixtiyoriy: Mini App initData HMAC bilan tekshiriladi

Foydalanuvchi:
    * Telegram Mini App + TELEGRAM_BOT_TOKEN: initData'dagi user.id (imzo tekshirilgan).
    * Aks holda: qurilma ID (brauzer localStorage, X-Device-Id) va IP. IP'ga alohida, kattaroq
      limit (FREE_DAILY_LIMIT * IP_FACTOR): localStorage'ni tozalab cheksiz savol olib bo'lmaydi,
      bitta Wi-Fi ortidagi bir necha kishi esa bir-biriga xalaqit bermaydi.

Hisoblagich data/state/quota.sqlite da (data/ git'ga tushmaydi). Qurilma ID va IP xeshlangan
holda saqlanadi. Kun Toshkent vaqti bilan hisoblanadi.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from .. import config, llm

IP_FACTOR = 4
INIT_DATA_MAX_AGE = 7 * 86400  # Telegram initData imzosi shuncha vaqt yaroqli
_DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Tashkent")
except Exception:  # noqa: BLE001 - tzdata yo'q tizim
    _TZ = timezone(timedelta(hours=5))


def _int_env(name: str, default: int) -> int:
    llm.load_env()
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except ValueError:
        return default


def free_limit() -> int:
    return _int_env("FREE_DAILY_LIMIT", 5)


def global_limit() -> int:
    return _int_env("GLOBAL_DAILY_LIMIT", 100)


def today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:24]


# ---------------------------------------------------------------- Telegram initData
def telegram_user_id(init_data: str, bot_token: str, now: float | None = None) -> int | None:
    """initData imzosi to'g'ri bo'lsa user.id, aks holda None.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    got = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not got or not hmac.compare_digest(want, got):
        return None
    try:
        if (now or time.time()) - int(pairs.get("auth_date", "0")) > INIT_DATA_MAX_AGE:
            return None
        uid = json.loads(pairs.get("user", "{}")).get("id")
        return int(uid) if uid else None
    except (ValueError, TypeError, AttributeError):
        return None


def _public_ip(s: str) -> bool:
    try:
        a = ipaddress.ip_address(s)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_unspecified)


def client_ip(host: str | None, headers) -> str:
    """Foydalanuvchi IP'si (bepul limit va rate limit uchun).

    * Server cloudflared / nginx ortida (so'rov 127.0.0.1 dan) bo'lsa - CF-Connecting-IP yoki X-Forwarded-For.
    * TRUST_PROXY=1 (Hugging Face Spaces: so'rov HF proksisi orqali, ichki tarmoq manzilidan keladi) -
      X-Forwarded-For dagi O'NGDAN birinchi ochiq (public) IP. Chap tomonini foydalanuvchi o'zi yozishi mumkin
      ("X-Forwarded-For: 1.2.3.4" yuborib boshqa odamdek ko'rinish), o'ng tomonini esa proksi qo'shadi.
    * Aks holda sarlavhalarga ishonilmaydi (soxtalashtirish mumkin)."""
    host = host or "?"
    xff = [p.strip() for p in (headers.get("x-forwarded-for") or "").split(",") if p.strip()]
    if os.environ.get("TRUST_PROXY") == "1" and xff:
        for p in reversed(xff):
            if _public_ip(p):
                return p
        return xff[-1]
    if host in ("127.0.0.1", "::1", "localhost"):
        fwd = headers.get("cf-connecting-ip") or (xff[0] if xff else "")
        if fwd:
            return fwd
    return host


def identity(host: str | None, headers) -> tuple[str, list[tuple[str, int]]]:
    """(tur, [(hisoblagich kaliti, limit), ...]). Savol barcha hisoblagichlar limitdan past bo'lsa o'tadi."""
    n = free_limit()
    tg = telegram_user_id(headers.get("x-telegram-init-data", ""), os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    if tg:
        return "telegram", [(f"tg:{tg}", n)]
    ip = client_ip(host, headers)
    dev = headers.get("x-device-id", "")
    keys = [(f"ip:{_h(ip)}", n * IP_FACTOR)]
    if _DEVICE_RE.match(dev):
        keys.insert(0, (f"dev:{_h(dev)}", n))
    else:  # qurilma ID yo'q: faqat IP, lekin oddiy foydalanuvchi limiti bilan
        keys = [(f"ip:{_h(ip)}", n)]
    return "device", keys


# ---------------------------------------------------------------- hisoblagich
class Quota:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or os.environ.get("DALIL_QUOTA_DB") or config.STATE / "quota.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT, key TEXT, n INTEGER NOT NULL DEFAULT 0, "
                         "PRIMARY KEY (day, key))")
        self._db.execute("DELETE FROM usage WHERE day < ?", ((datetime.now(_TZ) - timedelta(days=7)).strftime("%Y-%m-%d"),))

    def _used(self, day: str, key: str) -> int:
        r = self._db.execute("SELECT n FROM usage WHERE day=? AND key=?", (day, key)).fetchone()
        return r[0] if r else 0

    def status(self, keys: list[tuple[str, int]]) -> dict:
        """{limit, used, left, reason}: reason = None | "user" | "global"."""
        day, g = today(), global_limit()
        with self._lock:
            used_g = self._used(day, "*")
            per = [(self._used(day, k), lim) for k, lim in keys]
        limit = keys[0][1] if keys else 0
        used = per[0][0] if per else 0
        left_user = min((lim - u for u, lim in per), default=0)
        left = max(0, min(left_user, g - used_g))
        reason = None if left > 0 else ("global" if g - used_g <= 0 < left_user else "user")
        return {"limit": limit, "used": min(used, limit), "left": left, "reason": reason}

    def reserve(self, keys: list[tuple[str, int]]) -> bool:
        """Limit qolgan bo'lsa barcha hisoblagichlarni +1 qiladi (atomar)."""
        day, g = today(), global_limit()
        with self._lock:
            if self._used(day, "*") >= g or any(self._used(day, k) >= lim for k, lim in keys):
                return False
            self._db.execute("BEGIN")
            for k in ["*"] + [k for k, _ in keys]:
                self._db.execute("INSERT INTO usage(day, key, n) VALUES(?, ?, 1) "
                                 "ON CONFLICT(day, key) DO UPDATE SET n = n + 1", (day, k))
            self._db.execute("COMMIT")
            return True

    def refund(self, keys: list[tuple[str, int]]):
        """LLM umuman javob bermagan bo'lsa savol hisobga olinmaydi."""
        day = today()
        with self._lock:
            self._db.execute("BEGIN")
            for k in ["*"] + [k for k, _ in keys]:
                self._db.execute("UPDATE usage SET n = MAX(0, n - 1) WHERE day=? AND key=?", (day, k))
            self._db.execute("COMMIT")
