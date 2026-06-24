from pathlib import Path

import pytest
from pydantic import ValidationError

from quiet_chaos.config import AppConfig, TrafficMode, load_config


def test_default_config_is_bounded() -> None:
    config = AppConfig()

    assert config.max_requests_per_second == 1.0
    assert config.per_domain_cooldown_seconds == 30.0
    assert TrafficMode.DNS in config.modes


def test_load_config_from_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
log_level = "debug"
max_requests_per_second = 0.5
modes = ["http", "dns"]
seed_urls = ["https://example.com/"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.log_level == "debug"
    assert config.max_requests_per_second == 0.5
    assert config.modes == [TrafficMode.HTTP, TrafficMode.DNS]


def test_rate_limit_cannot_exceed_one_request_per_second() -> None:
    with pytest.raises(ValidationError):
        AppConfig(max_requests_per_second=2.0)
