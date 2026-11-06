from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from quiet_chaos.config import TrendConfig
from quiet_chaos.trend_sources import registrable_domain, retry_after


class BudgetExceeded(Exception):
    pass


class DailyBudget:
    def __init__(self, path: Path, config: TrendConfig) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.config = config
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS daily "
                "(day TEXT PRIMARY KEY, requests INTEGER NOT NULL, bytes INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS domains "
                "(day TEXT NOT NULL, domain TEXT NOT NULL, requests INTEGER NOT NULL, "
                "PRIMARY KEY(day, domain))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS backoff (domain TEXT PRIMARY KEY, until REAL NOT NULL)"
            )

    def reserve(self, url: str, max_bytes: int, now: datetime | None = None) -> tuple[str, int]:
        now = now or datetime.now(UTC)
        domain = registrable_domain(url)
        if domain is None:
            raise BudgetExceeded("Invalid HTTPS destination")
        day = now.date().isoformat()
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cooldown = connection.execute(
                "SELECT until FROM backoff WHERE domain = ?", (domain,)
            ).fetchone()
            if cooldown and cooldown[0] > now.timestamp():
                raise BudgetExceeded("Domain is cooling down")
            daily = connection.execute(
                "SELECT requests, bytes FROM daily WHERE day = ?", (day,)
            ).fetchone() or (0, 0)
            domain_count = connection.execute(
                "SELECT requests FROM domains WHERE day = ? AND domain = ?", (day, domain)
            ).fetchone()
            if daily[0] >= self.config.daily_requests or (
                domain_count and domain_count[0] >= self.config.daily_domain_requests
            ):
                raise BudgetExceeded("Daily request budget exhausted")
            allowance = min(max_bytes, self.config.daily_response_bytes - daily[1])
            if allowance <= 0:
                raise BudgetExceeded("Daily response budget exhausted")
            connection.execute(
                "INSERT INTO daily VALUES (?, 1, ?) ON CONFLICT(day) "
                "DO UPDATE SET requests = requests + 1, bytes = bytes + excluded.bytes",
                (day, allowance),
            )
            connection.execute(
                "INSERT INTO domains VALUES (?, ?, 1) ON CONFLICT(day, domain) "
                "DO UPDATE SET requests = requests + 1",
                (day, domain),
            )
        return day, allowance

    def settle(self, day: str, allowance: int, received: int) -> None:
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute(
                "UPDATE daily SET bytes = bytes - ? + ? WHERE day = ?",
                (allowance, received, day),
            )

    def backoff(self, url: str, value: str | None, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        domain = registrable_domain(url)
        if domain is None:
            return
        until = retry_after(value, now).timestamp()
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute(
                "INSERT INTO backoff VALUES (?, ?) ON CONFLICT(domain) "
                "DO UPDATE SET until = MAX(until, excluded.until)",
                (domain, until),
            )

    def exhausted(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        with sqlite3.connect(self.path, timeout=30) as connection:
            daily = connection.execute(
                "SELECT requests, bytes FROM daily WHERE day = ?", (now.date().isoformat(),)
            ).fetchone()
        return bool(
            daily
            and (
                daily[0] >= self.config.daily_requests
                or daily[1] >= self.config.daily_response_bytes
            )
        )
