from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from quiet_chaos.budget import BudgetExceeded, DailyBudget
from quiet_chaos.config import AppConfig, TrendConfig
from quiet_chaos.health import RuntimeStats
from quiet_chaos.seed_sources import SeedStore
from quiet_chaos.telemetry import Telemetry
from quiet_chaos.traffic import TrafficGenerator


def test_daily_limits_are_shared_and_reset(tmp_path: Path) -> None:
    config = TrendConfig(daily_domain_requests=1, daily_requests=2, daily_response_bytes=20)
    first = DailyBudget(tmp_path / "budget.db", config)
    second = DailyBudget(tmp_path / "budget.db", config)
    now = datetime(2026, 11, 6, tzinfo=UTC)
    day, allowance = first.reserve("https://www.example.co.uk/", 10, now)
    first.settle(day, allowance, 3)
    with pytest.raises(BudgetExceeded):
        second.reserve("https://other.example.co.uk/", 10, now)
    second.reserve("https://example.com/", 10, now)
    assert first.exhausted(now)
    assert not first.exhausted(now + timedelta(days=1))


def test_backoff_persists(tmp_path: Path) -> None:
    config = TrendConfig()
    first = DailyBudget(tmp_path / "budget.db", config)
    now = datetime(2026, 11, 6, tzinfo=UTC)
    first.backoff("https://example.com/", "120", now)
    second = DailyBudget(tmp_path / "budget.db", config)
    with pytest.raises(BudgetExceeded):
        second.reserve("https://www.example.com/", 1, now + timedelta(seconds=119))
    second.reserve("https://example.com/", 1, now + timedelta(seconds=120))


async def test_redirect_hops_and_rate_limit_are_enforced(tmp_path: Path) -> None:
    config = AppConfig(seed_sources=[], trend_sources={"daily_domain_requests": 1})
    budget = DailyBudget(tmp_path / "budget.db", config.trend_sources)
    generator = TrafficGenerator(
        config,
        SeedStore(config, tmp_path),
        RuntimeStats.start(),
        Telemetry(False, "test"),
        budget=budget,
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await generator._safe_request(client, "GET", "https://example.com/") is None
    assert requests == ["https://example.com/"]


async def test_http_rate_limit_blocks_later_requests(tmp_path: Path) -> None:
    config = AppConfig(seed_sources=[], trend_sources={"daily_domain_requests": 10})
    budget = DailyBudget(tmp_path / "budget.db", config.trend_sources)
    generator = TrafficGenerator(
        config,
        SeedStore(config, tmp_path),
        RuntimeStats.start(),
        Telemetry(False, "test"),
        budget=budget,
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(429, headers={"retry-after": "3600"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await generator._safe_request(client, "GET", "https://example.com/")
        assert await generator._safe_request(client, "GET", "https://example.com/other") is None
    assert requests == ["https://example.com/"]
