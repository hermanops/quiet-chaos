from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from urllib.parse import urlparse


class RateLimiter:
    def __init__(self, max_requests_per_second: float, per_domain_cooldown_seconds: float) -> None:
        self._global_interval = 1 / max_requests_per_second
        self._per_domain_cooldown_seconds = per_domain_cooldown_seconds
        self._last_global_at = 0.0
        self._last_domain_at: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def wait_for(self, url: str) -> None:
        domain = urlparse(url).hostname or ""
        async with self._lock:
            now = time.monotonic()
            wait_seconds = max(
                self._global_interval - (now - self._last_global_at),
                self._per_domain_cooldown_seconds - (now - self._last_domain_at[domain]),
                0.0,
            )
            if wait_seconds:
                await asyncio.sleep(wait_seconds)
            recorded_at = time.monotonic()
            self._last_global_at = recorded_at
            if domain:
                self._last_domain_at[domain] = recorded_at
