from datetime import UTC, datetime
from random import Random

import pytest

from quiet_chaos.config import PacingConfig
from quiet_chaos.pacing import diurnal_weight, next_pause_seconds


def test_pacing_can_be_disabled() -> None:
    pause = next_pause_seconds(PacingConfig(enabled=False), Random(1))

    assert pause == 0.0


def test_next_pause_seconds_uses_idle_range() -> None:
    config = PacingConfig(
        idle_min_seconds=1.0,
        idle_max_seconds=1.0,
        long_pause_probability=0.0,
    )

    pause = next_pause_seconds(config, Random(1))

    assert pause == 1.0


def test_diurnal_pacing_respects_max_pause() -> None:
    config = PacingConfig(
        idle_min_seconds=10.0,
        idle_max_seconds=10.0,
        long_pause_probability=0.0,
        diurnal_enabled=True,
        max_pause_seconds=5.0,
    )

    pause = next_pause_seconds(config, Random(1), now=datetime(2026, 1, 1, 3, 0))

    assert pause == 5.0
    assert 0.05 <= diurnal_weight(3.0) <= 1.0


@pytest.mark.parametrize(
    ("timezone", "instant", "local_hour"),
    [
        ("UTC", datetime(2026, 3, 8, 7, tzinfo=UTC), 7),
        ("America/New_York", datetime(2026, 3, 8, 6, 30, tzinfo=UTC), 1.5),
        ("America/New_York", datetime(2026, 3, 8, 7, 30, tzinfo=UTC), 3.5),
        ("Asia/Tokyo", datetime(2026, 3, 8, 7, tzinfo=UTC), 16),
    ],
)
def test_diurnal_pacing_converts_aware_instant(
    timezone: str, instant: datetime, local_hour: float
) -> None:
    config = PacingConfig(
        idle_min_seconds=1,
        idle_max_seconds=1,
        long_pause_probability=0,
        diurnal_enabled=True,
        timezone=timezone,
    )
    assert next_pause_seconds(config, Random(1), instant) == pytest.approx(
        1 / diurnal_weight(local_hour)
    )


def test_diurnal_timezone_requires_aware_injected_time() -> None:
    config = PacingConfig(diurnal_enabled=True, timezone="UTC")
    with pytest.raises(ValueError, match="aware datetime"):
        next_pause_seconds(config, Random(1), datetime(2026, 1, 1))


def test_diurnal_without_timezone_preserves_injected_local_hour() -> None:
    config = PacingConfig(
        idle_min_seconds=1,
        idle_max_seconds=1,
        long_pause_probability=0,
        diurnal_enabled=True,
    )
    assert next_pause_seconds(config, Random(1), datetime(2026, 1, 1, 3)) == pytest.approx(
        1 / diurnal_weight(3)
    )


@pytest.mark.parametrize("timezone", ["", "Not/AZone", "/etc/localtime"])
def test_pacing_config_rejects_unknown_timezone(timezone: str) -> None:
    with pytest.raises(ValueError, match="Unknown IANA timezone"):
        PacingConfig(timezone=timezone)
