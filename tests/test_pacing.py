from datetime import datetime
from random import Random

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
