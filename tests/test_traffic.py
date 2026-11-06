import asyncio
import socket

import httpx
import pytest

from quiet_chaos.config import AppConfig
from quiet_chaos.downloads import SourceTooLargeError
from quiet_chaos.health import RuntimeStats
from quiet_chaos.safety import SafetyTransport
from quiet_chaos.seed_sources import SeedStore
from quiet_chaos.telemetry import Telemetry
from quiet_chaos.traffic import TrafficGenerator


def make_generator(config: AppConfig | None = None) -> TrafficGenerator:
    config = config or AppConfig(seed_sources=[])
    return TrafficGenerator(
        config=config,
        seeds=SeedStore(config, cache_dir=None),  # type: ignore[arg-type]
        stats=RuntimeStats.start(),
        telemetry=Telemetry(False, "test"),
    )


def test_extract_links_normalizes_and_filters() -> None:
    generator = make_generator()

    links = generator._extract_links(
        '<a href="/about">About</a><a href="javascript:void(0)">Bad</a>',
        "https://example.com/",
    )

    assert links == ["https://example.com/about"]


def test_extract_assets_finds_common_assets() -> None:
    generator = make_generator()

    assets = generator._extract_assets(
        '<img src="/logo.png"><script src="https://cdn.example.com/app.js"></script>',
        "https://example.com/",
    )

    assert sorted(assets) == ["https://cdn.example.com/app.js", "https://example.com/logo.png"]


def test_extract_links_skips_visited_urls() -> None:
    generator = make_generator()
    generator._visited.add("https://example.com/about")

    links = generator._extract_links('<a href="/about">About</a>', "https://example.com/")

    assert links == []


def test_choose_url_can_reinject_root_seed() -> None:
    config = AppConfig(
        seed_sources=[],
        seed_reinjection_probability=1.0,
    )
    generator = make_generator(config)
    generator._links = ["https://linked.example/"]
    generator._seeds._urls = ["https://seed.example/"]

    assert generator._choose_url() == "https://seed.example/"


@pytest.mark.parametrize("missing_status", [404, 410])
async def test_rss_poll_reaches_last_path_after_missing_feeds(missing_status: int) -> None:
    generator = make_generator(AppConfig(seed_sources=[], seed_urls=["https://example.com/"]))
    generator._seeds._urls = ["https://example.com/"]
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/atom.xml":
            return httpx.Response(
                200,
                text='<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                "<title>News</title><id>urn:news:1</id></entry></feed>",
            )
        return httpx.Response(missing_status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await generator._rss_poll(client)

    assert paths == ["/feed", "/rss", "/rss.xml", "/atom.xml"]
    assert not generator._failures.is_blocked("https://example.com/")
    assert generator._stats.requests_attempted == 4
    assert generator._stats.requests_failed == 3
    assert generator._stats.requests_succeeded == 1


async def test_rss_missing_paths_stay_cached_after_other_request_succeeds() -> None:
    generator = make_generator(AppConfig(seed_sources=[], seed_urls=["https://example.com/"]))
    generator._seeds._urls = ["https://example.com/"]
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200 if request.url.path == "/" else 404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await generator._rss_poll(client)
        await generator._safe_request(client, "GET", "https://example.com/")
        await generator._rss_poll(client)

    assert paths == ["/feed", "/rss", "/rss.xml", "/atom.xml", "/"]
    assert generator._stats.requests_failed == 4
    assert not generator._failures.is_blocked("https://example.com/")


@pytest.mark.parametrize("status", [403, 429, 500])
async def test_rss_poll_preserves_real_failure_cooldown(status: int) -> None:
    generator = make_generator(
        AppConfig(seed_sources=[], seed_urls=["https://example.com/"], failure_cooldown_threshold=1)
    )
    generator._seeds._urls = ["https://example.com/"]
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await generator._rss_poll(client)
        assert await generator._safe_request(client, "GET", "https://example.com/") is None

    assert paths == ["/feed"]
    assert generator._failures.is_blocked("https://example.com/")


async def test_non_rss_missing_response_still_fails_without_retry() -> None:
    generator = make_generator(AppConfig(seed_sources=[], failure_cooldown_threshold=1))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await generator._safe_request(client, "GET", "https://example.com/feed")

    assert len(calls) == 1
    assert generator._failures.is_blocked("https://example.com/")


async def test_safe_request_retries_transient_failure() -> None:
    config = AppConfig(
        seed_sources=[],
        max_request_retries=1,
        retry_backoff_seconds=0,
    )
    generator = make_generator(config)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary failure", request=request)
        return httpx.Response(200, request=request, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await generator._safe_request(client, "GET", "https://example.com/")

    assert response is not None
    assert response.text == "ok"
    assert calls == 2


async def test_pacing_pause_respects_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(
        seed_sources=[],
        pacing={
            "idle_min_seconds": 10.0,
            "idle_max_seconds": 10.0,
            "long_pause_probability": 0.0,
        },
    )
    generator = make_generator(config)
    sleeps = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("quiet_chaos.traffic.asyncio.sleep", fake_sleep)
    deadline = generator._rng.random()  # keep rng advanced independently of loop timing
    deadline = __import__("asyncio").get_running_loop().time() + 0.25

    await generator._pause_between_actions(deadline)

    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 0.25


async def test_safe_request_does_not_retry_blocked_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = make_generator()
    resolutions = []
    calls = []

    async def resolve(*args, **kwargs):
        resolutions.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    transport = SafetyTransport(
        generator._safety, httpx.MockTransport(lambda request: calls.append(request))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.UnsupportedProtocol):
            await generator._safe_request(client, "GET", "https://example.com/")
    assert len(resolutions) == 1
    assert calls == []
    assert generator._stats.requests_succeeded == 0


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


async def test_safe_request_limits_body_and_closes_without_retry() -> None:
    generator = make_generator(
        AppConfig(seed_sources=[], max_response_bytes=1024, failure_cooldown_threshold=1)
    )
    stream = TrackedStream([b"x" * 1025, b"unread"])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceTooLargeError):
            await generator._safe_request(client, "GET", "https://example.com/")

    assert stream.closed
    assert stream.reads == 1
    assert len(calls) == 1
    assert generator._stats.requests_succeeded == 0
    assert generator._failures.is_blocked("https://example.com/")


async def test_safe_request_does_not_read_redirect_body() -> None:
    generator = make_generator()
    stream = TrackedStream([b"x" * 2_000_000])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(302, headers={"location": "/final"}, stream=stream)
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        response = await generator._safe_request(client, "GET", "https://example.com/")

    assert response is not None
    assert response.text == "ok"
    assert response.url.path == "/final"
    assert stream.closed
    assert stream.reads == 0


async def test_safe_request_head_ignores_advertised_body_length() -> None:
    generator = make_generator()
    stream = TrackedStream([b"must not read"])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-length": "9999999999"}, stream=stream
            )
        )
    ) as client:
        response = await generator._safe_request(client, "HEAD", "https://example.com/")
    assert response is not None
    assert response.content == b""
    assert response.headers["content-length"] == "9999999999"
    assert stream.closed
    assert stream.reads == 0
    assert generator._stats.response_body_bytes_received == 0


async def test_safe_request_counts_streamed_bytes() -> None:
    generator = make_generator()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=TrackedStream([b"hello", b"world"]))
        )
    ) as client:
        response = await generator._safe_request(client, "GET", "https://example.com/")
    assert response is not None
    assert response.content == b"helloworld"
    assert generator._stats.response_body_bytes_received == 10


async def test_safe_request_enforces_redirect_limit() -> None:
    generator = make_generator()
    streams = []

    def handler(request: httpx.Request) -> httpx.Response:
        stream = TrackedStream([b"not read"])
        streams.append(stream)
        return httpx.Response(302, headers={"location": "/again"}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), max_redirects=2) as client:
        with pytest.raises(httpx.TooManyRedirects):
            await generator._safe_request(client, "GET", "https://example.com/")
    assert len(streams) == 3
    assert all(stream.closed and stream.reads == 0 for stream in streams)


async def test_run_once_scrubs_error_message_from_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = make_generator(AppConfig(seed_sources=[], modes=["dns"]))

    async def fail_lookup():
        raise ValueError("sensitive https://internal.example/path")

    monkeypatch.setattr(generator, "_dns_lookup", fail_lookup)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)) as client:
        await generator.run_once(client)
    assert generator._stats.last_error == "ValueError"
    assert generator._stats.requests_failed == 1


@pytest.mark.parametrize(
    ("addresses", "allowed"),
    [
        (["93.184.215.14"], True),
        (["127.0.0.1"], False),
        (["10.0.0.1", "93.184.215.14"], False),
        ([], False),
    ],
)
async def test_dns_lookup_validates_answers_and_sets_lifetime(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str], allowed: bool
) -> None:
    generator = make_generator(AppConfig(seed_sources=[], seed_urls=["https://example.com/"]))
    generator._seeds._urls = ["https://example.com/"]
    calls = []

    def resolve(host, record_type, *, lifetime):
        calls.append((host, record_type, lifetime))
        return addresses

    monkeypatch.setattr(generator._resolver, "resolve", resolve)
    if allowed:
        await generator._dns_lookup()
    else:
        with pytest.raises(httpx.UnsupportedProtocol):
            await generator._dns_lookup()
    assert calls == [("example.com", "A", generator._config.request_timeout_seconds)]
    assert generator._stats.dns_lookups == int(allowed)


@pytest.mark.parametrize("url", ["https://localhost/", "http://10.0.0.1/", "https://blocked.test/"])
async def test_dns_lookup_does_not_resolve_denied_url(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    generator = make_generator(
        AppConfig(seed_sources=[], seed_urls=[url], deny_domains=["localhost", "blocked.test"])
    )
    generator._seeds._urls = [url]

    def unexpected_resolution(*args, **kwargs):
        pytest.fail("Denied URL must not be resolved")

    monkeypatch.setattr(generator._resolver, "resolve", unexpected_resolution)
    await generator._dns_lookup()
    assert generator._stats.dns_lookups == 0


async def test_dns_lookup_timeout_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import dns.exception

    generator = make_generator(AppConfig(seed_sources=[], modes=["dns"]))

    def resolve(*args, **kwargs):
        raise dns.exception.Timeout()

    monkeypatch.setattr(generator._resolver, "resolve", resolve)
    async with httpx.AsyncClient() as client:
        await generator.run_once(client)
    assert generator._stats.dns_lookups == 0
    assert generator._stats.requests_failed == 1
    assert generator._stats.last_error == "Timeout"


@pytest.mark.parametrize("status", [200, 500])
async def test_safe_request_rejects_headers_without_reading_body(status: int) -> None:
    generator = make_generator()
    stream = TrackedStream([b"must not read"])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status, headers={"content-length": "9999999999"}, stream=stream
            )
        )
    ) as client:
        expected = SourceTooLargeError if status == 200 else httpx.HTTPStatusError
        with pytest.raises(expected):
            await generator._safe_request(client, "GET", "https://example.com/")
    assert stream.closed
    assert stream.reads == 0


async def test_safe_request_closes_failed_stream_before_retry() -> None:
    generator = make_generator(AppConfig(seed_sources=[], retry_backoff_seconds=0))

    class TimeoutStream(TrackedStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadTimeout("transient read timeout")

    failed = TimeoutStream([])
    succeeded = TrackedStream([b"done"])
    streams = []

    def handler(request: httpx.Request) -> httpx.Response:
        if streams:
            assert failed.closed
        stream = failed if not streams else succeeded
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await generator._safe_request(client, "GET", "https://example.com/")
    assert response is not None
    assert response.text == "done"
    assert len(streams) == 2
    assert all(stream.closed for stream in streams)
    assert generator._stats.response_body_bytes_received == 11


async def test_safe_request_closes_stream_on_cancellation() -> None:
    generator = make_generator()

    class CancelledStream(TrackedStream):
        async def __aiter__(self):
            yield b"partial"
            raise asyncio.CancelledError

    stream = CancelledStream([])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(asyncio.CancelledError):
            await generator._safe_request(client, "GET", "https://example.com/")
    assert stream.closed
    assert generator._stats.requests_succeeded == 0
    assert generator._stats.response_body_bytes_received == 7
