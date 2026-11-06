from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import asdict
from datetime import UTC, datetime
from urllib.parse import quote_plus, urljoin, urlparse

import dns.resolver
import feedparser
import httpx
from bs4 import BeautifulSoup

from quiet_chaos.bounded import FailureCooldown, LRUSet
from quiet_chaos.budget import BudgetExceeded, DailyBudget
from quiet_chaos.config import AppConfig, TrafficMode
from quiet_chaos.defaults import DEFAULT_SEARCH_QUERIES
from quiet_chaos.downloads import read_response_limited
from quiet_chaos.fingerprints import browser_headers
from quiet_chaos.health import RuntimeStats
from quiet_chaos.pacing import next_pause_seconds
from quiet_chaos.safety import SafetyPolicy, SafetyTransport
from quiet_chaos.seed_sources import SeedStore
from quiet_chaos.telemetry import Telemetry
from quiet_chaos.trend_sources import TrendStore

LOGGER = logging.getLogger(__name__)


class TrafficGenerator:
    def __init__(
        self,
        config: AppConfig,
        seeds: SeedStore,
        stats: RuntimeStats,
        telemetry: Telemetry,
        trend_store: TrendStore | None = None,
        budget: DailyBudget | None = None,
        trend_snapshot: dict | None = None,
    ) -> None:
        self._config = config
        self._seeds = seeds
        self._stats = stats
        self._telemetry = telemetry
        self._trend_store = trend_store
        self._budget = budget
        self._trend_snapshot = trend_snapshot
        self._trend_day = None
        self._trend_urls: list[str] = []
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
        trend_task = None
        if self._config.stats_log.enabled:
            stats_task = asyncio.create_task(self._log_stats_forever())
        if self._trend_store is not None:
            trend_task = asyncio.create_task(self._refresh_trends_forever())
        async with httpx.AsyncClient(
            follow_redirects=True,
            transport=SafetyTransport(self._safety),
            trust_env=False,
            timeout=self._config.request_timeout_seconds,
            headers={
                "accept": "text/html,application/xhtml+xml,application/rss+xml;q=0.9,*/*;q=0.8"
            },
        ) as client:
            try:
                while deadline is None or asyncio.get_running_loop().time() < deadline:
                    if self._budget is not None and self._budget.exhausted():
                        LOGGER.info("daily traffic budget exhausted")
                        break
                    await self.run_once(client)
                    await self._pause_between_actions(deadline)
            finally:
                if stats_task is not None:
                    stats_task.cancel()
                    await asyncio.gather(stats_task, return_exceptions=True)
                if trend_task is not None:
                    trend_task.cancel()
                    await asyncio.gather(trend_task, return_exceptions=True)

    async def run_once(self, client: httpx.AsyncClient) -> None:
        if self._trend_store is not None and self._trend_snapshot is not None:
            today = datetime.now(UTC).date()
            if self._trend_day != today:
                self._trend_urls = self._trend_store.pool(self._trend_snapshot, today)
                self._trend_day = today
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
                self._stats.last_error = type(error).__name__
                LOGGER.warning(
                    "traffic action failed", extra={"qc_error": f"{type(error).__name__}: {error}"}
                )

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
        if self._budget is not None and urlparse(url).scheme != "https":
            return
        if not self._safety.is_allowed_url(url):
            return
        host = urlparse(url).hostname
        if not host:
            return
        reservation = None
        if self._budget is not None:
            try:
                reservation = self._budget.reserve(url, 1)
            except BudgetExceeded:
                LOGGER.info("dns lookup skipped by budget", extra={"qc_domain": host})
                return
        try:
            answer = await asyncio.to_thread(
                self._resolver.resolve, host, "A", lifetime=self._config.request_timeout_seconds
            )
        finally:
            if reservation is not None and self._budget is not None:
                self._budget.settle(*reservation, 0)
        addresses = [str(record) for record in answer]
        if not addresses or not all(self._safety.is_public_address(value) for value in addresses):
            raise httpx.UnsupportedProtocol("DNS answer blocked by safety policy")
        self._stats.dns_lookups += 1
        LOGGER.info("dns lookup", extra={"qc_domain": host})

    async def _rss_poll(self, client: httpx.AsyncClient) -> None:
        root = self._choose_url()
        for path in ("/feed", "/rss", "/rss.xml", "/atom.xml"):
            candidate = urljoin(root, path)
            response = await self._safe_request(client, "GET", candidate, allow_missing=True)
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
        self, client: httpx.AsyncClient, method: str, url: str, *, allow_missing: bool = False
    ) -> httpx.Response | None:
        if method not in {"GET", "HEAD"} or not self._safety.is_allowed_url(url):
            return None
        if url in self._visited:
            LOGGER.debug("skipping visited url", extra={"qc_url": url})
            return None
        if self._failures.is_blocked(url):
            LOGGER.debug("skipping cooled-down domain", extra={"qc_url": url})
            return None
        headers = browser_headers(random.choice(self._config.user_agents))
        self._stats.requests_attempted += 1
        LOGGER.info("request", extra={"qc_method": method, "qc_url": url})
        try:
            response = await self._request_with_retries(client, method, url, headers)
        except BudgetExceeded:
            LOGGER.info(
                "traffic request skipped by budget", extra={"qc_domain": urlparse(url).hostname}
            )
            return None
        except httpx.HTTPStatusError as error:
            if allow_missing and error.response.status_code in {404, 410}:
                self._stats.requests_failed += 1
                self._visited.add(url)
                LOGGER.debug(
                    "feed path missing",
                    extra={"qc_url": url, "qc_status": error.response.status_code},
                )
                return None
            self._failures.record_failure(url)
            raise
        except httpx.HTTPError:
            self._failures.record_failure(url)
            raise
        self._stats.requests_succeeded += 1
        self._visited.add(url)
        self._failures.record_success(url)
        return response

    def _choose_url(self) -> str:
        if self._links and self._rng.random() < self._config.seed_reinjection_probability:
            return (
                self._rng.choice(self._seeds.urls + self._trend_urls)
                if self._trend_urls
                else self._seeds.choose()
            )
        candidates = [
            url
            for url in (self._links or self._seeds.urls + self._trend_urls)
            if url not in self._visited and not self._failures.is_blocked(url)
        ]
        if not candidates:
            return (
                self._rng.choice(self._seeds.urls + self._trend_urls)
                if self._trend_urls
                else self._seeds.choose()
            )
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
                return await self._request_bounded(client, method, url, headers)
            except (httpx.HTTPStatusError, httpx.UnsupportedProtocol):
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

    async def _request_bounded(
        self, client: httpx.AsyncClient, method: str, url: str, headers: dict[str, str]
    ) -> httpx.Response:
        request = client.build_request(
            method, url, headers={**headers, "accept-encoding": "gzip, deflate"}
        )
        history: list[httpx.Response] = []
        while True:
            if len(history) > client.max_redirects:
                raise httpx.TooManyRedirects("Exceeded maximum allowed redirects", request=request)
            reservation = None
            if self._budget is not None:
                if request.method not in {"GET", "HEAD"} or request.url.scheme != "https":
                    raise BudgetExceeded("Only HTTPS GET and HEAD are allowed")
                client.cookies.clear()
                request.headers.pop("cookie", None)
                reservation = self._budget.reserve(
                    str(request.url), self._config.max_response_bytes
                )
            try:
                response = await client.send(request, stream=True, follow_redirects=False)
            except BaseException:
                if reservation is not None and self._budget is not None:
                    self._budget.settle(*reservation, 0)
                raise
            try:
                if self._budget is not None and response.status_code in {429, 503}:
                    self._budget.backoff(str(request.url), response.headers.get("retry-after"))
                    LOGGER.info(
                        "domain rate limited",
                        extra={"qc_status": response.status_code, "qc_domain": request.url.host},
                    )
                if response.next_request is not None:
                    history.append(response)
                    request = response.next_request
                    continue
                response.raise_for_status()
                content = (
                    await read_response_limited(
                        response, reservation[1] if reservation else self._config.max_response_bytes
                    )
                    if method != "HEAD"
                    else b""
                )
                response_headers = response.headers.copy()
                if method != "HEAD":
                    response_headers.pop("content-encoding", None)
                    response_headers.pop("transfer-encoding", None)
                    response_headers["content-length"] = str(len(content))
                result = httpx.Response(
                    response.status_code,
                    headers=response_headers,
                    content=content,
                    request=response.request,
                    extensions=response.extensions,
                    history=history,
                )
                result.encoding = response.encoding
                return result
            finally:
                self._stats.response_body_bytes_received += response.num_bytes_downloaded
                if reservation is not None and self._budget is not None:
                    self._budget.settle(*reservation, response.num_bytes_downloaded)
                await response.aclose()

    async def _refresh_trends_forever(self) -> None:
        if self._trend_store is None:
            return
        while True:
            await asyncio.sleep(self._config.trend_sources.refresh_hours * 3600)
            snapshot = await self._trend_store.refresh()
            if snapshot is not None:
                self._trend_snapshot = snapshot
                self._trend_day = None

    async def _pause_between_actions(self, deadline: float | None = None) -> None:
        pause_seconds = next_pause_seconds(self._config.pacing, self._rng)
        if self._budget is not None:
            pause_seconds = max(pause_seconds, 1.0)
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
