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
    kind: Literal["tranco_zip", "text"] = "tranco_zip"
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


class AppConfig(BaseModel):
    log_level: str = "info"
    json_logs: bool = True
    run_for_seconds: int | None = Field(default=None, ge=1)
    max_requests_per_second: float = Field(default=1.0, gt=0, le=1.0)
    per_domain_cooldown_seconds: float = Field(default=30.0, ge=0)
    request_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    max_response_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    max_links_per_page: int = Field(default=30, ge=1, le=500)
    modes: list[TrafficMode] = Field(default_factory=lambda: list(TrafficMode))
    seed_urls: list[HttpUrl] = Field(default_factory=lambda: DEFAULT_SEED_URLS.copy())
    seed_sources: list[SeedSource] = Field(default_factory=lambda: [SeedSource()])
    deny_domains: list[str] = Field(default_factory=lambda: DEFAULT_DENY_DOMAINS.copy())
    user_agents: list[str] = Field(default_factory=lambda: DEFAULT_USER_AGENTS.copy())
    search_queries: list[str] = Field(default_factory=list)
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
