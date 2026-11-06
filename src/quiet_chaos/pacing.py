from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from quiet_chaos.config import PacingConfig


def diurnal_weight(hour: float) -> float:
    daytime = 0.5 + 0.5 * math.cos(((hour - 16) / 24) * 2 * math.pi)
    evening = max(0.0, math.cos(((hour - 20) / 6) * math.pi) * 0.35)
    return max(0.05, min(1.0, daytime + evening))


def next_pause_seconds(
    config: PacingConfig,
    rng: random.Random,
    now: datetime | None = None,
) -> float:
    if not config.enabled:
        return 0.0
    if rng.random() < config.long_pause_probability:
        pause = rng.uniform(config.long_pause_min_seconds, config.long_pause_max_seconds)
    else:
        pause = rng.uniform(config.idle_min_seconds, config.idle_max_seconds)

    if config.diurnal_enabled:
        if config.timezone is None:
            current = now or datetime.now().astimezone()
        else:
            current = now or datetime.now(UTC)
            if current.utcoffset() is None:
                raise ValueError("An aware datetime is required with pacing.timezone")
            current = current.astimezone(ZoneInfo(config.timezone))
        hour = current.hour + current.minute / 60
        pause *= 1 / diurnal_weight(hour)
    return min(pause, config.max_pause_seconds)
