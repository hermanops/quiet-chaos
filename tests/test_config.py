from pathlib import Path

from quiet_chaos.config import AppConfig, TrafficMode, load_config


def test_default_config_is_bounded() -> None:
    config = AppConfig()

    assert config.user_agent_source.enabled is False
    assert config.visited_url_cache_size == 5_000
    assert config.pacing.enabled is True
    assert config.stats_log.interval_seconds == 300
    assert config.max_request_retries == 1
    assert TrafficMode.DNS in config.modes


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
