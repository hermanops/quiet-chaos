import httpx
import pytest

from quiet_chaos.config import AppConfig
from quiet_chaos.health import RuntimeStats
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
