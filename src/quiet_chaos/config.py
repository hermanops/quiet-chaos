from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from quiet_chaos.defaults import DEFAULT_DENY_DOMAINS, DEFAULT_SEED_URLS, DEFAULT_USER_AGENTS


class TrafficMode(StrEnum):
    HTTP = "http"
    DNS = "dns"
    RSS = "rss"
    SEARCH = "search"
    ASSETS = "assets"


class SeedSource(BaseModel):
    kind: Literal["tranco_zip", "crux_gzip_csv", "text"] = "tranco_zip"
    url: HttpUrl = Field(default="https://tranco-list.eu/top-1m.csv.zip")
    limit: int = Field(default=500, ge=1, le=10_000)
    refresh_hours: int = Field(default=24, ge=1, le=168)


class HealthConfig(BaseModel):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)


class TelemetryConfig(BaseModel):
    enabled: bool = False
    service_name: str = "quiet-chaos"


class UserAgentSourceConfig(BaseModel):
    enabled: bool = False
    url: HttpUrl = Field(default="https://www.useragents.me")
    limit: int = Field(default=50, ge=1, le=500)
    refresh_hours: int = Field(default=168, ge=1, le=720)


class PacingConfig(BaseModel):
    enabled: bool = True
    idle_min_seconds: float = Field(default=0.25, ge=0, le=60)
    idle_max_seconds: float = Field(default=2.0, ge=0, le=300)
    long_pause_probability: float = Field(default=0.02, ge=0, le=1)
    long_pause_min_seconds: float = Field(default=60.0, ge=0, le=3_600)
    long_pause_max_seconds: float = Field(default=300.0, ge=0, le=7_200)
    max_pause_seconds: float = Field(default=300.0, ge=0, le=7_200)
    diurnal_enabled: bool = False

    @model_validator(mode="after")
    def require_ordered_ranges(self) -> PacingConfig:
        if self.idle_min_seconds > self.idle_max_seconds:
            msg = "idle_min_seconds must be less than or equal to idle_max_seconds"
            raise ValueError(msg)
        if self.long_pause_min_seconds > self.long_pause_max_seconds:
            msg = "long_pause_min_seconds must be less than or equal to long_pause_max_seconds"
            raise ValueError(msg)
        return self


class StatsLogConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = Field(default=300, ge=10, le=86_400)


class AppConfig(BaseModel):
    log_level: str = "info"
    json_logs: bool = True
    run_for_seconds: int | None = Field(default=None, ge=1)
    request_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    max_response_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    max_links_per_page: int = Field(default=30, ge=1, le=500)
    visited_url_cache_size: int = Field(default=5_000, ge=0, le=500_000)
    failure_cooldown_threshold: int = Field(default=3, ge=1, le=10)
    failure_cooldown_seconds: float = Field(default=300.0, ge=0, le=86_400)
    failure_cache_size: int = Field(default=1_000, ge=0, le=100_000)
    max_request_retries: int = Field(default=1, ge=0, le=3)
    retry_backoff_seconds: float = Field(default=1.0, ge=0, le=30)
    seed_reinjection_probability: float = Field(default=0.1, ge=0, le=1)
    modes: list[TrafficMode] = Field(default_factory=lambda: list(TrafficMode))
    seed_urls: list[HttpUrl] = Field(default_factory=lambda: DEFAULT_SEED_URLS.copy())
    seed_sources: list[SeedSource] = Field(default_factory=lambda: [SeedSource()])
    deny_domains: list[str] = Field(default_factory=lambda: DEFAULT_DENY_DOMAINS.copy())
    user_agents: list[str] = Field(default_factory=lambda: DEFAULT_USER_AGENTS.copy())
    user_agent_source: UserAgentSourceConfig = Field(default_factory=UserAgentSourceConfig)
    search_queries: list[str] = Field(default_factory=list)
    pacing: PacingConfig = Field(default_factory=PacingConfig)
    stats_log: StatsLogConfig = Field(default_factory=StatsLogConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"debug", "info", "warning", "error", "critical"}:
            msg = "log_level must be debug, info, warning, error, or critical"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def require_modes(self) -> AppConfig:
        if not self.modes:
            msg = "at least one traffic mode must be enabled"
            raise ValueError(msg)
        if not self.user_agents:
            msg = "at least one user agent is required"
            raise ValueError(msg)
        return self


def load_config(path: Path | None) -> AppConfig:
    if path is None:
        return AppConfig()
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return AppConfig.model_validate(raw)
