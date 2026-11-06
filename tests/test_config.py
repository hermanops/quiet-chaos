import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from quiet_chaos.config import AppConfig, TrafficMode, load_config


def test_package_version_matches_metadata() -> None:
    from quiet_chaos import __version__

    metadata = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert tomllib.loads(metadata.read_text(encoding="utf-8"))["project"]["version"] == __version__


def test_default_config_is_bounded() -> None:
    config = AppConfig()

    assert config.user_agent_source.enabled is False
    assert config.visited_url_cache_size == 5_000
    assert config.pacing.enabled is True
    assert config.stats_log.interval_seconds == 300
    assert config.max_request_retries == 1
    assert config.health.host == "127.0.0.1"
    assert config.health.allowed_hosts == []
    assert TrafficMode.DNS in config.modes
    assert config.trend_sources.enabled is True
    assert config.trend_sources.pool_size == 30
    assert config.trend_sources.refresh_hours == 24
    assert config.trend_sources.daily_domain_requests == 10
    assert config.trend_sources.daily_requests == 500
    assert config.trend_sources.daily_response_bytes == 100 * 1024 * 1024


def test_trend_configuration_can_be_disabled_and_is_bounded(tmp_path: Path) -> None:
    config_file = tmp_path / "trends.toml"
    config_file.write_text(
        "[trend_sources]\nenabled = false\npool_size = 20\ndaily_requests = 50\n",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.trend_sources.enabled is False
    assert config.trend_sources.pool_size == 20
    assert config.trend_sources.daily_requests == 50
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"trend_sources": {"daily_requests": 0}})
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"trend_sources": {"crux_url": "http://example.com/"}})
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"trend_sources": {"crux_url": "https://user:pass@example.com/"}})


def test_load_config_from_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
log_level = "debug"
modes = ["http", "dns"]
seed_urls = ["https://example.com/"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.log_level == "debug"
    assert config.modes == [TrafficMode.HTTP, TrafficMode.DNS]


def test_example_configs_inherit_safe_defaults() -> None:
    from quiet_chaos.defaults import DEFAULT_DENY_DOMAINS
    from quiet_chaos.safety import SafetyPolicy

    root = Path(__file__).resolve().parents[1]
    for name, duration in [("config.toml", 3600), ("config.srv.toml", None)]:
        config = load_config(root / "examples" / name)
        assert config.deny_domains == DEFAULT_DENY_DOMAINS
        assert config.run_for_seconds == duration
        assert config.max_response_bytes == 1_000_000
        assert config.trend_sources.daily_domain_requests == 10
        assert config.trend_sources.daily_requests == 500
        assert config.trend_sources.daily_response_bytes == 100 * 1024 * 1024
        assert not SafetyPolicy(config.deny_domains).is_allowed_url("http://172.17.0.1/")


def test_server_profile_inherits_example_topics() -> None:
    from quiet_chaos.defaults import DEFAULT_SEARCH_QUERIES, DEFAULT_SEED_URLS

    root = Path(__file__).resolve().parents[1]
    example = load_config(root / "examples" / "config.toml")
    server = load_config(root / "examples" / "config.srv.toml")

    assert {str(url) for url in example.seed_urls} <= {str(url) for url in server.seed_urls}
    assert {str(url) for url in server.seed_urls} == set(DEFAULT_SEED_URLS)
    assert set(example.search_queries) <= set(server.search_queries or DEFAULT_SEARCH_QUERIES)
    assert server.run_for_seconds is None
    assert server.pacing.diurnal_enabled is True
