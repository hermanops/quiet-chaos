from __future__ import annotations

import csv
import io
import random
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx

from quiet_chaos.config import AppConfig, SeedSource
from quiet_chaos.defaults import DEFAULT_SEED_URLS
from quiet_chaos.safety import SafetyPolicy


class SeedStore:
    def __init__(self, config: AppConfig, cache_dir: Path) -> None:
        self._config = config
        self._cache_dir = cache_dir
        self._safety = SafetyPolicy(config.deny_domains)
        self._urls: list[str] = []

    @property
    def urls(self) -> list[str]:
        return self._urls.copy()

    async def load(self, refresh: bool = False) -> list[str]:
        urls = [str(url) for url in self._config.seed_urls]
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            for source in self._config.seed_sources:
                urls.extend(await self._load_source(client, source, refresh))

        allowed = []
        seen = set()
        for url in urls or DEFAULT_SEED_URLS:
            normalized = self._normalize_seed_url(url)
            if normalized and normalized not in seen and self._safety.is_allowed_url(normalized):
                allowed.append(normalized)
                seen.add(normalized)

        self._urls = allowed or DEFAULT_SEED_URLS.copy()
        random.shuffle(self._urls)
        return self.urls

    def choose(self) -> str:
        if not self._urls:
            self._urls = DEFAULT_SEED_URLS.copy()
        return random.choice(self._urls)

    async def _load_source(
        self, client: httpx.AsyncClient, source: SeedSource, refresh: bool
    ) -> list[str]:
        cache_file = self._cache_dir / f"{source.kind}-{abs(hash(str(source.url)))}.cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if not refresh and self._is_fresh(cache_file, source.refresh_hours):
            return cache_file.read_text(encoding="utf-8").splitlines()[: source.limit]

        response = await client.get(str(source.url))
        response.raise_for_status()
        if source.kind == "tranco_zip":
            domains = self._parse_tranco_zip(response.content, source.limit)
        else:
            domains = self._parse_text_domains(response.text, source.limit)
        cache_file.write_text("\n".join(domains), encoding="utf-8")
        return domains

    @staticmethod
    def _is_fresh(path: Path, refresh_hours: int) -> bool:
        if not path.exists():
            return False
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        return datetime.now(UTC) - modified_at < timedelta(hours=refresh_hours)

    @staticmethod
    def _parse_tranco_zip(content: bytes, limit: int) -> list[str]:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            csv_name = archive.namelist()[0]
            rows = archive.read(csv_name).decode("utf-8", errors="replace").splitlines()
        domains: list[str] = []
        for row in csv.reader(rows):
            if len(row) >= 2:
                domains.append(f"https://{row[1].strip()}/")
            if len(domains) >= limit:
                break
        return domains

    @staticmethod
    def _parse_text_domains(text: str, limit: int) -> list[str]:
        domains: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            domain = stripped.split(",")[-1].strip()
            domains.append(f"https://{domain}/")
            if len(domains) >= limit:
                break
        return domains

    @staticmethod
    def _normalize_seed_url(url: str) -> str | None:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        if not parsed.hostname:
            return None
        scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
        path = parsed.path or "/"
        return f"{scheme}://{parsed.hostname}{path}"
