"""So'rovlar tezligi cheklovi (internetga ochiq server uchun): daqiqasiga va kuniga, xotirada.

Bepul limitdan (quota.py) farqi: u faqat server kaliti bilan LLM chaqirilgan savolni sanaydi va SQLite'da
saqlanadi; bu esa og'ir endpointlarga (qidiruv, embedding, OpenAI proksisi) har qanday so'rovni sanaydi -
botlar CPU'ni band qilmasligi va proksi ochiq "relay" bo'lib qolmasligi uchun. Server qayta ishga tushsa nolga qaytadi.

Kalitlar (har biri alohida, so'rov hammasidan o'tishi kerak):
    * qurilma: Telegram user.id (imzo tekshirilgan) yoki X-Device-Id;
    * IP: quota.client_ip (TRUST_PROXY=1 bo'lsa X-Forwarded-For dan), limiti RATE_IP_FACTOR barobar katta -
      bitta Wi-Fi ortidagi bir necha kishi bir-biriga xalaqit bermasin, X-Device-Id ni har safar almashtirib
      cheklovni chetlab o'tib bo'lmasin.

.env / Space secrets:
    RATE_LIMIT_PER_MIN=20     # bitta qurilmaga daqiqasiga (0 = cheklov yo'q)
    RATE_LIMIT_PER_DAY=400    # bitta qurilmaga kuniga
    RATE_IP_FACTOR=3          # IP limiti = qurilma limiti x shu son
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

from . import quota

# cheklanadigan yo'llar (prefiks bo'yicha)
LIMITED = ("/api/ask", "/api/context", "/api/search", "/api/verify", "/api/proxy/openai")
MAX_KEYS = 50_000  # xotira himoyasi: shuncha kalitdan oshsa eski yozuvlar tozalanadi


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except ValueError:
        return default


def per_min() -> int:
    return _int("RATE_LIMIT_PER_MIN", 20)


def per_day() -> int:
    return _int("RATE_LIMIT_PER_DAY", 400)


def ip_factor() -> int:
    return max(1, _int("RATE_IP_FACTOR", 3))


def limited(path: str) -> bool:
    return path.startswith(LIMITED)


def keys_for(host: str | None, headers) -> list[tuple[str, int]]:
    """[(kalit, ko'paytiruvchi)]: qurilma (yoki Telegram foydalanuvchisi) x1, IP x RATE_IP_FACTOR."""
    out: list[tuple[str, int]] = []
    kind, qkeys = quota.identity(host, headers)
    if kind == "telegram":
        out.append((qkeys[0][0], 1))
    else:
        dev = [k for k, _ in qkeys if k.startswith("dev:")]
        if dev:
            out.append((dev[0], 1))
    ip = quota.client_ip(host, headers)
    out.append((f"ip:{quota._h(ip)}", ip_factor() if out else 1))
    return out


class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._min: dict[str, deque] = {}
        self._day: dict[str, int] = {}
        self._today = quota.today()

    def check(self, keys: list[tuple[str, int]], now: float | None = None) -> tuple[bool, int, str]:
        """(ruxsat, Retry-After soniya, sabab "min" | "day" | ""). Ruxsat bo'lsa hamma hisoblagich +1."""
        pm, pd = per_min(), per_day()
        now = time.time() if now is None else now
        with self._lock:
            day = quota.today()
            if day != self._today:
                self._today, self._day = day, {}
            if len(self._min) > MAX_KEYS:
                self._min = {k: q for k, q in self._min.items() if q and q[-1] > now - 60}
            if len(self._day) > MAX_KEYS:
                self._day = {}
            for k, f in keys:
                if pd and self._day.get(k, 0) >= pd * f:
                    return False, 3600, "day"
                q = self._min.get(k)
                if q is not None:
                    while q and q[0] <= now - 60:
                        q.popleft()
                    if pm and len(q) >= pm * f:
                        return False, max(1, int(q[0] + 60 - now) + 1), "min"
            for k, _ in keys:
                self._min.setdefault(k, deque()).append(now)
                self._day[k] = self._day.get(k, 0) + 1
        return True, 0, ""
