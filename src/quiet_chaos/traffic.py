from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from urllib.parse import quote_plus, urljoin, urlparse

import dns.resolver
import feedparser
import httpx
from bs4 import BeautifulSoup

from quiet_chaos.config import AppConfig, TrafficMode
from quiet_chaos.defaults import DEFAULT_SEARCH_QUERIES
from quiet_chaos.health import RuntimeStats
from quiet_chaos.rate_limit import RateLimiter
from quiet_chaos.safety import SafetyPolicy
from quiet_chaos.seed_sources import SeedStore
from quiet_chaos.telemetry import Telemetry

LOGGER = logging.getLogger(__name__)


class TrafficGenerator:
    def __init__(
        self,
        config: AppConfig,
        seeds: SeedStore,
        rate_limiter: RateLimiter,
        stats: RuntimeStats,
        telemetry: Telemetry,
    ) -> None:
        self._config = config
        self._seeds = seeds
        self._rate_limiter = rate_limiter
        self._stats = stats
        self._telemetry = telemetry
        self._safety = SafetyPolicy(config.deny_domains)
        self._links: list[str] = []

    async def run_forever(self, stop_after_seconds: int | None = None) -> None:
        deadline = (
            asyncio.get_running_loop().time() + stop_after_seconds if stop_after_seconds else None
        )
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=self._config.request_timeout_seconds,
            headers={
                "accept": "text/html,application/xhtml+xml,application/rss+xml;q=0.9,*/*;q=0.8"
            },
        ) as client:
            while deadline is None or asyncio.get_running_loop().time() < deadline:
                await self.run_once(client)

    async def run_once(self, client: httpx.AsyncClient) -> None:
        mode = random.choice(self._config.modes)
        with self._telemetry.span(f"traffic.{mode}") as span:
            span.set_attribute("traffic.mode", str(mode))
            try:
                if mode == TrafficMode.HTTP:
                    await self._http_browse(client)
                elif mode == TrafficMode.DNS:
                    await self._dns_lookup()
                elif mode == TrafficMode.RSS:
                    await self._rss_poll(client)
                elif mode == TrafficMode.SEARCH:
                    await self._search_like(client)
                elif mode == TrafficMode.ASSETS:
                    await self._asset_fetch(client)
            except Exception as error:  # noqa: BLE001 - traffic generation should keep running.
                self._stats.requests_failed += 1
                self._stats.last_error = f"{type(error).__name__}: {error}"
                LOGGER.warning("traffic action failed", extra={"qc_error": self._stats.last_error})

    async def _http_browse(self, client: httpx.AsyncClient) -> None:
        url = self._choose_url()
        response = await self._safe_request(client, "GET", url)
        if response is None:
            return
        links = self._extract_links(str(response.text), str(response.url))
        if links:
            self._links = links[: self._config.max_links_per_page]

    async def _dns_lookup(self) -> None:
        url = self._choose_url()
        host = urlparse(url).hostname
        if not host:
            return
        resolver = dns.resolver.Resolver()
        await asyncio.to_thread(resolver.resolve, host, "A")
        self._stats.dns_lookups += 1
        LOGGER.info("dns lookup", extra={"qc_domain": host})

    async def _rss_poll(self, client: httpx.AsyncClient) -> None:
        root = self._choose_url()
        for path in ("/feed", "/rss", "/rss.xml", "/atom.xml"):
            candidate = urljoin(root, path)
            response = await self._safe_request(client, "GET", candidate)
            if response is None:
                continue
            parsed = feedparser.parse(response.text)
            if parsed.entries:
                LOGGER.info(
                    "rss feed discovered",
                    extra={"qc_url": candidate, "qc_entries": len(parsed.entries)},
                )
                return

    async def _search_like(self, client: httpx.AsyncClient) -> None:
        queries = self._config.search_queries or DEFAULT_SEARCH_QUERIES
        query = random.choice(queries)
        url = "https://en.wikipedia.org/w/api.php?action=opensearch&limit=5&format=json&search="
        await self._safe_request(client, "GET", f"{url}{quote_plus(query)}")

    async def _asset_fetch(self, client: httpx.AsyncClient) -> None:
        page_url = self._choose_url()
        response = await self._safe_request(client, "GET", page_url)
        if response is None:
            return
        assets = self._extract_assets(str(response.text), str(response.url))
        if assets:
            await self._safe_request(client, "HEAD", random.choice(assets))

    async def _safe_request(
        self, client: httpx.AsyncClient, method: str, url: str
    ) -> httpx.Response | None:
        if method not in {"GET", "HEAD"} or not self._safety.is_allowed_url(url):
            return None
        await self._rate_limiter.wait_for(url)
        headers = {"user-agent": random.choice(self._config.user_agents)}
        self._stats.requests_attempted += 1
        self._stats.last_url = url
        LOGGER.info("request", extra={"qc_method": method, "qc_url": url})
        response = await client.request(method, url, headers=headers)
        response.raise_for_status()
        self._stats.requests_succeeded += 1
        return response

    def _choose_url(self) -> str:
        candidates = self._links or self._seeds.urls
        if not candidates:
            return self._seeds.choose()
        return random.choice(candidates)

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html[: self._config.max_response_bytes], "html.parser")
        links = []
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            absolute = urljoin(base_url, href)
            if self._safety.is_allowed_url(absolute):
                links.append(absolute)
        random.shuffle(links)
        return links

    def _extract_assets(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html[: self._config.max_response_bytes], "html.parser")
        assets = []
        selectors = [("img[src]", "src"), ("script[src]", "src"), ("link[href]", "href")]
        for selector, attribute in selectors:
            for element in soup.select(selector):
                value = element.get(attribute)
                if not value:
                    continue
                absolute = urljoin(base_url, value)
                if self._safety.is_allowed_url(absolute):
                    assets.append(absolute)
        random.shuffle(assets)
        return assets

    async def close(self) -> None:
        with suppress(Exception):
            return None
