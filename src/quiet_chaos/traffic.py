from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import asdict
from urllib.parse import quote_plus, urljoin, urlparse

import dns.resolver
import feedparser
import httpx
from bs4 import BeautifulSoup

from quiet_chaos.bounded import FailureCooldown, LRUSet
from quiet_chaos.config import AppConfig, TrafficMode
from quiet_chaos.defaults import DEFAULT_SEARCH_QUERIES
from quiet_chaos.fingerprints import browser_headers
from quiet_chaos.health import RuntimeStats
from quiet_chaos.pacing import next_pause_seconds
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
        self._rng = random.Random()
        self._resolver = dns.resolver.Resolver()
        self._visited = LRUSet(config.visited_url_cache_size)
        self._failures = FailureCooldown(
            threshold=config.failure_cooldown_threshold,
            cooldown_seconds=config.failure_cooldown_seconds,
            max_size=config.failure_cache_size,
        )

    async def run_forever(self, stop_after_seconds: int | None = None) -> None:
        deadline = (
            asyncio.get_running_loop().time() + stop_after_seconds if stop_after_seconds else None
        )
        stats_task = None
        if self._config.stats_log.enabled:
            stats_task = asyncio.create_task(self._log_stats_forever())
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=self._config.request_timeout_seconds,
            headers={
                "accept": "text/html,application/xhtml+xml,application/rss+xml;q=0.9,*/*;q=0.8"
            },
        ) as client:
            try:
                while deadline is None or asyncio.get_running_loop().time() < deadline:
                    await self.run_once(client)
                    await self._pause_between_actions(deadline)
            finally:
                if stats_task is not None:
                    stats_task.cancel()
                    await asyncio.gather(stats_task, return_exceptions=True)

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
        await asyncio.to_thread(self._resolver.resolve, host, "A")
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
        if url in self._visited:
            LOGGER.debug("skipping visited url", extra={"qc_url": url})
            return None
        if self._failures.is_blocked(url):
            LOGGER.debug("skipping cooled-down domain", extra={"qc_url": url})
            return None
        await self._rate_limiter.wait_for(url)
        headers = browser_headers(random.choice(self._config.user_agents))
        self._stats.requests_attempted += 1
        self._stats.last_url = url
        LOGGER.info("request", extra={"qc_method": method, "qc_url": url})
        try:
            response = await self._request_with_retries(client, method, url, headers)
        except httpx.HTTPError:
            self._failures.record_failure(url)
            raise
        self._stats.requests_succeeded += 1
        self._visited.add(url)
        self._failures.record_success(url)
        return response

    def _choose_url(self) -> str:
        if self._links and self._rng.random() < self._config.seed_reinjection_probability:
            return self._seeds.choose()
        candidates = [
            url
            for url in (self._links or self._seeds.urls)
            if url not in self._visited and not self._failures.is_blocked(url)
        ]
        if not candidates:
            return self._seeds.choose()
        return self._rng.choice(candidates)

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: dict[str, str],
    ) -> httpx.Response:
        for attempt in range(self._config.max_request_retries + 1):
            try:
                response = await client.request(method, url, headers=headers)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError:
                raise
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= self._config.max_request_retries:
                    raise
                delay = self._config.retry_backoff_seconds * (2**attempt)
                delay += self._rng.uniform(0, min(0.5, self._config.retry_backoff_seconds))
                LOGGER.debug(
                    "transient request failure, retrying",
                    extra={"qc_url": url, "qc_retry_attempt": attempt + 1, "qc_retry_delay": delay},
                )
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable retry state")

    async def _pause_between_actions(self, deadline: float | None = None) -> None:
        pause_seconds = next_pause_seconds(self._config.pacing, self._rng)
        if pause_seconds <= 0:
            return
        if deadline is not None:
            remaining_seconds = deadline - asyncio.get_running_loop().time()
            if remaining_seconds <= 0:
                return
            pause_seconds = min(pause_seconds, remaining_seconds)
        LOGGER.debug("pacing pause", extra={"qc_pause_seconds": round(pause_seconds, 3)})
        await asyncio.sleep(pause_seconds)

    async def _log_stats_forever(self) -> None:
        while True:
            await asyncio.sleep(self._config.stats_log.interval_seconds)
            LOGGER.info(
                "runtime stats",
                extra={f"qc_{key}": value for key, value in asdict(self._stats).items()},
            )

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html[: self._config.max_response_bytes], "html.parser")
        links = []
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            absolute = urljoin(base_url, href)
            if self._safety.is_allowed_url(absolute) and absolute not in self._visited:
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
                if self._safety.is_allowed_url(absolute) and absolute not in self._visited:
                    assets.append(absolute)
        random.shuffle(assets)
        return assets
