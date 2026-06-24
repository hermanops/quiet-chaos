from __future__ import annotations

from urllib.parse import urlparse


class SafetyPolicy:
    def __init__(self, deny_domains: list[str]) -> None:
        self._deny_domains = [domain.lower() for domain in deny_domains]

    def is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        return not any(
            host == denied or host.endswith(f".{denied}") or host.startswith(denied)
            for denied in self._deny_domains
        )
