"""Bepul limit va Telegram initData tekshiruvi (LLM'siz, vaqtinchalik baza bilan).

    FREE_DAILY_LIMIT=2 GLOBAL_DAILY_LIMIT=3 .venv/bin/python scripts/test_quota.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FREE_DAILY_LIMIT", "2")
os.environ.setdefault("GLOBAL_DAILY_LIMIT", "3")
from lexrag.web import quota as Q  # noqa: E402


def signed_init_data(token: str, user_id: int, auth_date: int) -> str:
    """Telegram'ning o'zi kabi imzolangan initData"""
    f = {"auth_date": str(auth_date), "query_id": "AAEtest", "user": json.dumps({"id": user_id, "first_name": "Test"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(f)


def check(name: str, got, want):
    ok = got == want
    print(f"{'OK ' if ok else 'XATO'} {name}: {got!r}" + ("" if ok else f" (kutilgan {want!r})"))
    return ok


def main():
    tok = "123456:TEST-TOKEN"
    init = signed_init_data(tok, 777, int(time.time()))
    res = [
        check("tg: to'g'ri imzo", Q.telegram_user_id(init, tok), 777),
        check("tg: boshqa bot tokeni", Q.telegram_user_id(init, "1:other"), None),
        check("tg: user.id o'zgartirilgan", Q.telegram_user_id(init.replace("777", "778"), tok), None),
        check("tg: 8 kunlik eski imzo", Q.telegram_user_id(init, tok, now=time.time() + 8 * 86400), None),
        check("tg: token yo'q", Q.telegram_user_id(init, ""), None),
        check("ip: cloudflared ortida", Q.client_ip("127.0.0.1", {"cf-connecting-ip": "9.9.9.9"}), "9.9.9.9"),
        check("ip: tashqi so'rov sarlavhasiga ishonilmaydi", Q.client_ip("8.8.8.8", {"x-forwarded-for": "1.1.1.1"}), "8.8.8.8"),
    ]
    q = Q.Quota(Path(tempfile.mkdtemp()) / "q.sqlite")
    a = Q.identity("1.2.3.4", {"x-device-id": "devAAAAAAAA1"})[1]
    b = Q.identity("1.2.3.4", {"x-device-id": "devBBBBBBBB2"})[1]
    c = Q.identity("5.6.7.8", {"x-device-id": "devCCCCCCCC3"})[1]
    res += [
        check("A: boshida", q.status(a)["left"], 2),
        check("A: 1, 2 o'tadi, 3 yo'q", [q.reserve(a), q.reserve(a), q.reserve(a)], [True, True, False]),
        check("A: tugadi (user)", q.status(a), {"limit": 2, "used": 2, "left": 0, "reason": "user"}),
        check("B (shu IP, boshqa qurilma)", q.reserve(b), True),
        check("C: umumiy limit 3 tugagan", q.reserve(c), False),
        check("C: sabab global", q.status(c)["reason"], "global"),
    ]
    q.refund(b)
    res.append(check("B: xato bo'lgan savol qaytarildi", q.status(b)["used"], 0))
    res.append(check("B: umumiydan 1 ta bo'shadi", q.status(b)["left"], 1))
    print("\nHammasi to'g'ri" if all(res) else "\nXATOLAR BOR")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
