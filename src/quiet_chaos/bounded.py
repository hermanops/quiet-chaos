from __future__ import annotations

import time
from collections import OrderedDict
from urllib.parse import urlparse


class LRUSet:
    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._items: OrderedDict[str, None] = OrderedDict()

    def __contains__(self, value: str) -> bool:
        return value in self._items

    def add(self, value: str) -> None:
        if self._max_size <= 0:
            return
        if value in self._items:
            self._items.move_to_end(value)
        self._items[value] = None
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)


class FailureCooldown:
    def __init__(self, threshold: int, cooldown_seconds: float, max_size: int) -> None:
        self._threshold = threshold
        self._cooldown_seconds = cooldown_seconds
        self._max_size = max_size
        self._failures: OrderedDict[str, tuple[int, float]] = OrderedDict()

    def is_blocked(self, url: str) -> bool:
        key = self._key(url)
        entry = self._failures.get(key)
        if entry is None:
            return False
        count, blocked_at = entry
        if count < self._threshold:
            return False
        if time.monotonic() - blocked_at < self._cooldown_seconds:
            return True
        self._failures.pop(key, None)
        return False

    def record_failure(self, url: str) -> None:
        if self._max_size <= 0:
            return
        key = self._key(url)
        count, _ = self._failures.get(key, (0, 0.0))
        self._failures[key] = (count + 1, time.monotonic())
        self._failures.move_to_end(key)
        while len(self._failures) > self._max_size:
            self._failures.popitem(last=False)

    def record_success(self, url: str) -> None:
        self._failures.pop(self._key(url), None)

    @staticmethod
    def _key(url: str) -> str:
        return urlparse(url).hostname or url
