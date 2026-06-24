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
