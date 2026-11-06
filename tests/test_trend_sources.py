from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import quiet_chaos.trend_sources as trend_sources
from quiet_chaos.cli import app
from quiet_chaos.config import AppConfig, TrendConfig
from quiet_chaos.safety import SafetyPolicy
from quiet_chaos.trend_sources import (
    TrendStore,
    candidate_decision,
    normalize_ranks,
    parse_crux,
    parse_majestic,
    parse_radar,
    parse_ranked_zip,
    registrable_domain,
    select_daily,
    weighted_score,
)


def test_provider_parsers() -> None:
    radar = json.dumps({"success": True, "result": {"top_0": [{"domain": "a.com", "rank": 1}]}})
    assert parse_radar(radar.encode()) == {"a.com": 1}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("top.csv", "1,a.com\n2,b.com\n")
    assert parse_ranked_zip(archive.getvalue(), 2) == {"a.com": 1, "b.com": 2}
    assert parse_majestic(b"GlobalRank,Domain\n1,a.com\n", 10) == {"a.com": 1}
    assert parse_crux(gzip.compress(b"origin,rank\nhttps://a.com,1000\n"), 10) == {
        "https://a.com": 1000
    }
    with pytest.raises(ValueError):
        parse_radar(b'{"success": false}')


def test_ranked_zip_stops_at_limit_within_decompression_bound() -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("top.csv", "1,a.com\n2,b.com\n")

    assert parse_ranked_zip(archive.getvalue(), limit=1, max_bytes=8) == {"a.com": 1}
    with pytest.raises(httpx.HTTPError, match="Decompressed source exceeds"):
        parse_ranked_zip(archive.getvalue(), limit=2, max_bytes=8)


def test_domains_and_filters() -> None:
    policy = SafetyPolicy(["blocked.co.uk"])
    assert registrable_domain("www.example.co.uk") == "example.co.uk"
    assert registrable_domain("user.github.io") == "user.github.io"
    assert registrable_domain("127.0.0.1") is None
    assert registrable_domain("http://example.com") is None
    assert normalize_ranks({"x.example.co.uk": 3, "example.co.uk": 5}, policy) == {
        "example.co.uk": 3
    }
    config = TrendConfig(categories={"example.co.uk": ["news"]}, deny_categories=["news"])
    assert candidate_decision("example.co.uk", config, policy) == "denied_category"
    assert candidate_decision("blocked.co.uk", config, policy) == "safety"


def test_score_and_selection() -> None:
    assert weighted_score({"umbrella": 10}, {"umbrella": 100}, 50, 100) > weighted_score(
        {"umbrella": 100}, {"umbrella": 100}, 50, 100
    )
    candidates = {f"domain{number}.com": number for number in range(1, 40)}
    first = select_daily(candidates, "abc", date(2026, 11, 6), 20)
    assert first == select_daily(candidates, "abc", date(2026, 11, 6), 20)
    assert len(set(first)) == 20
    assert first != select_daily(candidates, "abc", date(2026, 11, 7), 20)


async def test_refresh_history_replay_and_failure_fallback(tmp_path: Path) -> None:
    calls: list[str] = []
    rank = 10
    fail = False

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if fail:
            return httpx.Response(503)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("top.csv", f"{rank},example.com\n")
        return httpx.Response(200, content=archive.getvalue(), headers={"etag": '"test"'})

    config = AppConfig(seed_sources=[], trend_sources={"enabled": True})
    store = TrendStore(config, tmp_path)
    now = datetime(2026, 11, 1, tzinfo=UTC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await store.refresh(now, client)
        assert first is not None
        assert len(calls) == 2
        assert await store.refresh(now + timedelta(hours=1), client) == first
        assert len(calls) == 2
        rank = 5
        later = await store.refresh(now + timedelta(days=7), client)
        assert later is not None
        assert later["candidates"][0]["momentum"] == 0.5
        path = next(store.directory.glob(f"snapshot-*{later['snapshot_hash']}.json"))
        assert store.replay(path) == later
        assert store.pool(later, now.date()) == ["https://example.com/"]
        corrupted = tmp_path / "corrupted.json"
        corrupted.write_text(path.read_text().replace("example.com", "attacker.com"))
        with pytest.raises(ValueError, match="Invalid trend snapshot"):
            store.replay(corrupted)
        fail = True
        assert await store.refresh(now + timedelta(days=8), client) == later
        assert store.latest() == later
        fail = False
        rank = 2
        monthly = await store.refresh(now + timedelta(days=28), client)
        assert monthly is not None
        assert monthly["candidates"][0]["momentum"] == pytest.approx(0.7)


async def test_radar_token_not_forwarded_or_logged(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("QUIET_CHAOS_RADAR_TOKEN", "test-secret-token")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.cloudflare.com":
            return httpx.Response(302, headers={"location": "https://example.com/"})
        return httpx.Response(503)

    store = TrendStore(AppConfig(seed_sources=[]), tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await store.refresh(datetime(2026, 11, 6, tzinfo=UTC), client) is None
    assert all(request.url.host != "example.com" for request in requests)
    assert "test-secret-token" not in caplog.text


async def test_failed_atomic_publication_keeps_last_snapshot(tmp_path: Path, monkeypatch) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("top.csv", "1,example.com\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=archive.getvalue())

    store = TrendStore(AppConfig(seed_sources=[]), tmp_path)
    now = datetime(2026, 11, 6, tzinfo=UTC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        original = await store.refresh(now, client)
        write = trend_sources._atomic_write

        def fail_pointer(path: Path, content: bytes) -> None:
            if path.name == "latest":
                raise OSError("simulated publication failure")
            write(path, content)

        monkeypatch.setattr(trend_sources, "_atomic_write", fail_pointer)
        assert await store.refresh(now + timedelta(days=1), client) == original
    assert store.latest() == original


def test_cli_replay_is_offline(tmp_path: Path, monkeypatch) -> None:
    snapshot = {
        "version": 1,
        "created_at": "2026-11-06T00:00:00+00:00",
        "sources": {},
        "candidates": [{"domain": "example.com", "score": 1, "decision": "accepted"}],
        "rejected": [],
    }
    snapshot["snapshot_hash"] = trend_sources.hashlib.sha256(
        trend_sources._canonical(snapshot)
    ).hexdigest()
    path = tmp_path / "snapshot.json"
    path.write_bytes(trend_sources._canonical(snapshot))

    async def unexpected_refresh(*args: object, **kwargs: object) -> None:
        raise AssertionError("replay must be offline")

    monkeypatch.setattr(TrendStore, "refresh", unexpected_refresh)
    result = CliRunner().invoke(
        app,
        ["trends", "--cache-dir", str(tmp_path), "--snapshot", str(path), "--date", "2026-11-06"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["origins"] == ["https://example.com/"]
