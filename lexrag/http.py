"""Saytga ehtiyotkor HTTP klient: pauza, retry, exponential backoff."""
from __future__ import annotations

import logging
import random
import time

import httpx

from . import config

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class PoliteClient:
    def __init__(self, delay_range=config.DELAY_RANGE, max_retries=config.MAX_RETRIES):
        self.delay_range = delay_range
        self.max_retries = max_retries
        self._last = 0.0
        self.client = httpx.Client(
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "uz,ru;q=0.8,en;q=0.6",
            },
            follow_redirects=True,
            timeout=config.TIMEOUT,
        )

    def _wait(self):
        pause = random.uniform(*self.delay_range)
        elapsed = time.monotonic() - self._last
        if elapsed < pause:
            time.sleep(pause - elapsed)

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        err = None
        for attempt in range(1, self.max_retries + 1):
            self._wait()
            try:
                r = self.client.request(method, url, **kw)
                self._last = time.monotonic()
                if r.status_code in RETRY_STATUS:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                self._last = time.monotonic()
                err = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status is not None and status not in RETRY_STATUS:
                    raise  # 404 va h.k. - qayta urinishdan foyda yo'q
                backoff = min(120, 2 ** attempt) + random.uniform(0, 1.5)
                ra = getattr(getattr(e, "response", None), "headers", {}).get("Retry-After") if status else None
                if ra and ra.isdigit():
                    backoff = max(backoff, int(ra))
                log.warning("%s %s -> %s (urinish %d/%d), %.1fs kutaman",
                            method, url, e, attempt, self.max_retries, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"{url}: {self.max_retries} urinishdan keyin ham xato: {err}")

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
