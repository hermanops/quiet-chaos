from quiet_chaos.config import AppConfig
from quiet_chaos.health import RuntimeStats
from quiet_chaos.rate_limit import RateLimiter
from quiet_chaos.seed_sources import SeedStore
from quiet_chaos.telemetry import Telemetry
from quiet_chaos.traffic import TrafficGenerator


def make_generator() -> TrafficGenerator:
    config = AppConfig(seed_sources=[], per_domain_cooldown_seconds=0)
    return TrafficGenerator(
        config=config,
        seeds=SeedStore(config, cache_dir=None),  # type: ignore[arg-type]
        rate_limiter=RateLimiter(1, 0),
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
