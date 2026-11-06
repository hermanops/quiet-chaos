from __future__ import annotations

import csv
import gzip
import hashlib
import io
import ipaddress
import json
import logging
import math
import os
import random
import re
import sqlite3
import tempfile
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import tldextract

from quiet_chaos.config import AppConfig, TrendConfig
from quiet_chaos.downloads import (
    MAX_SOURCE_BYTES,
    SourceTooLargeError,
    read_decompressed_limited,
    read_response_limited,
)
from quiet_chaos.safety import SafetyPolicy, SafetyTransport

_SUFFIX = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
LOGGER = logging.getLogger(__name__)
RADAR_URL = "https://api.cloudflare.com/client/v4/radar/ranking/top?name=top&limit=100"
TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
UMBRELLA_URL = "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip"
MAJESTIC_URL = "https://downloads.majestic.com/majestic_million.csv"


def registrable_domain(value: str) -> str | None:
    try:
        parts = urlsplit(value if "://" in value else f"https://{value}")
        if parts.scheme != "https" or parts.username or parts.password or parts.port:
            return None
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        if len(host) > 253 or not all(_LABEL.fullmatch(label) for label in host.split(".")):
            return None
        extracted = _SUFFIX(host)
        if not extracted.suffix or not extracted.domain:
            return None
        return f"{extracted.domain}.{extracted.suffix}"
    except (UnicodeError, ValueError):
        return None


def parse_radar(content: bytes) -> dict[str, int]:
    payload = json.loads(content)
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Invalid Radar response")
    rows = payload["result"]["top_0"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Empty Radar ranking")
    ranks: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("domain"), str):
            raise ValueError("Invalid Radar ranking")
        rank = row.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or not 1 <= rank <= 100:
            raise ValueError("Invalid Radar rank")
        ranks[row["domain"]] = rank
    return ranks


def parse_ranked_zip(
    content: bytes, limit: int, max_bytes: int = MAX_SOURCE_BYTES
) -> dict[str, int]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise ValueError("Expected one ranking CSV")
        with archive.open(names[0]) as stream:
            ranks: dict[str, int] = {}
            total = 0
            first_row = True
            while len(ranks) < limit:
                remaining = max_bytes - total
                line = stream.readline(remaining + 1)
                if not line:
                    break
                total += len(line)
                if total > max_bytes:
                    raise SourceTooLargeError(f"Decompressed source exceeds {max_bytes} bytes")
                text = line.decode("utf-8-sig" if first_row else "utf-8")
                first_row = False
                row = next(csv.reader([text]))
                if len(row) != 2:
                    raise ValueError("Invalid ranking row")
                rank = int(row[0])
                if rank < 1:
                    raise ValueError("Invalid rank")
                ranks[row[1].strip()] = rank
    if not ranks:
        raise ValueError("Empty ranking")
    return ranks


def parse_majestic(content: bytes, limit: int) -> dict[str, int]:
    rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    if not rows.fieldnames or not {"GlobalRank", "Domain"} <= set(rows.fieldnames):
        raise ValueError("Invalid Majestic header")
    ranks: dict[str, int] = {}
    for row in rows:
        rank = int(row["GlobalRank"])
        if rank < 1:
            raise ValueError("Invalid Majestic rank")
        ranks[row["Domain"].strip()] = rank
        if len(ranks) >= limit:
            break
    if not ranks:
        raise ValueError("Empty Majestic ranking")
    return ranks


def parse_crux(content: bytes, limit: int) -> dict[str, int]:
    with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
        data = read_decompressed_limited(stream, MAX_SOURCE_BYTES)
    rows = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if not rows.fieldnames or not {"origin", "rank"} <= set(rows.fieldnames):
        raise ValueError("Invalid CrUX header")
    ranks: dict[str, int] = {}
    for row in rows:
        rank = int(row["rank"])
        if rank not in {1000, 10000, 100000, 1000000}:
            raise ValueError("Invalid CrUX bucket")
        ranks[row["origin"].strip()] = rank
        if len(ranks) >= limit:
            break
    if not ranks:
        raise ValueError("Empty CrUX list")
    return ranks


def normalize_ranks(ranks: dict[str, int], policy: SafetyPolicy) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for raw, rank in ranks.items():
        domain = registrable_domain(raw)
        original = raw if "://" in raw else f"https://{raw}/"
        if (
            domain
            and policy.is_allowed_url(original)
            and policy.is_allowed_url(f"https://{domain}/")
        ):
            normalized[domain] = min(rank, normalized.get(domain, rank))
    return normalized


def candidate_decision(domain: str, config: TrendConfig, policy: SafetyPolicy) -> str:
    if not policy.is_allowed_url(f"https://{domain}/"):
        return "safety"
    if config.allow_domains and domain not in config.allow_domains:
        return "not_allowed_domain"
    if any(domain == denied or domain.endswith(f".{denied}") for denied in config.deny_domains):
        return "denied_domain"
    categories = set(config.categories.get(domain, []))
    if categories.intersection(config.deny_categories):
        return "denied_category"
    if config.allow_categories and not categories.intersection(config.allow_categories):
        return "not_allowed_category"
    return "accepted"


def weighted_score(
    current: dict[str, int], previous: dict[str, int], baseline_rank: int | None, limit: int
) -> float:
    improvements = [
        max(0.0, min(1.0, (previous[name] - rank) / max(previous[name], 1)))
        for name, rank in current.items()
        if name in previous
    ]
    terms: list[tuple[float, float]] = []
    if improvements:
        terms.append((0.6, sum(improvements) / len(improvements)))
    if baseline_rank is not None:
        terms.append((0.3, max(0.0, 1 - (baseline_rank - 1) / max(limit - 1, 1))))
    terms.append((0.1, min(len(current) / 2, 1.0)))
    return sum(weight * score for weight, score in terms) / sum(weight for weight, _ in terms)


def select_daily(
    candidates: dict[str, float], snapshot_hash: str, day: date, size: int
) -> list[str]:
    seed = hashlib.sha256(f"{snapshot_hash}:{day.isoformat()}".encode()).digest()
    rng = random.Random(seed)
    keys = [
        (-math.log(1.0 - rng.random()) / max(score, 0.000001), domain)
        for domain, score in sorted(candidates.items())
    ]
    return [domain for _, domain in sorted(keys)[:size]]


def _canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


class TrendStore:
    def __init__(self, config: AppConfig, cache_dir: Path) -> None:
        self.config = config.trend_sources
        self.policy = SafetyPolicy(config.deny_domains)
        self.directory = cache_dir / "trends"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "refresh.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS refresh "
                "(provider TEXT PRIMARY KEY, attempted REAL NOT NULL, blocked_until REAL NOT NULL)"
            )

    def _claim(self, provider: str, now: datetime) -> bool:
        with sqlite3.connect(self.database, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempted, blocked_until FROM refresh WHERE provider = ?", (provider,)
            ).fetchone()
            timestamp = now.timestamp()
            if row and timestamp < max(row[0] + self.config.refresh_hours * 3600, row[1]):
                return False
            connection.execute(
                "INSERT INTO refresh VALUES (?, ?, 0) ON CONFLICT(provider) "
                "DO UPDATE SET attempted = excluded.attempted",
                (provider, timestamp),
            )
            return True

    def _block(self, provider: str, until: datetime) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE refresh SET blocked_until = MAX(blocked_until, ?) WHERE provider = ?",
                (until.timestamp(), provider),
            )

    def _observations(self, provider: str) -> list[dict]:
        result = []
        for path in sorted(self.directory.glob(f"{provider}-*.json")):
            try:
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != path.stem.rsplit("-", 1)[-1]:
                    continue
                data = json.loads(content)
                if data.get("provider") == provider and isinstance(data.get("ranks"), dict):
                    result.append(data)
            except (OSError, ValueError, TypeError):
                continue
        return result

    def _save_observation(self, data: dict) -> None:
        content = _canonical(data)
        digest = hashlib.sha256(content).hexdigest()
        stamp = data["retrieved_at"].replace(":", "-")
        path = self.directory / f"{data['provider']}-{stamp}-{digest}.json"
        if not path.exists():
            _atomic_write(path, content)

    async def _fetch(
        self, client: httpx.AsyncClient, provider: str, url: str, now: datetime
    ) -> dict:
        headers = {"accept-encoding": "gzip, deflate"}
        if provider == "radar":
            token = os.environ.get("QUIET_CHAOS_RADAR_TOKEN", "").strip()
            if not token:
                raise ValueError("Radar token unavailable")
            headers["authorization"] = f"Bearer {token}"
        for redirect in range(6):
            parsed_url = urlsplit(url)
            if (
                parsed_url.scheme != "https"
                or parsed_url.username
                or parsed_url.password
                or not self.policy.is_allowed_url(url)
            ):
                raise ValueError("Source URL blocked")
            client.cookies.clear()
            async with client.stream(
                "GET", url, headers=headers, follow_redirects=False
            ) as response:
                if response.status_code in {429, 503}:
                    self._block(provider, retry_after(response.headers.get("retry-after"), now))
                if response.is_redirect:
                    if provider == "radar" or redirect == 5:
                        raise ValueError("Source redirect blocked")
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                maximum = 128 * 1024 * 1024 if provider == "majestic" else MAX_SOURCE_BYTES
                content = await read_response_limited(response, maximum)
                etag = response.headers.get("etag")
                modified = response.headers.get("last-modified")
                break
        else:
            raise ValueError("Too many source redirects")
        if provider == "radar":
            if token.encode() in content or any(
                token in (value or "") for value in (etag, modified)
            ):
                raise ValueError("Radar response contains credentials")
            ranks = parse_radar(content)
            metadata = json.loads(content).get("result", {}).get("meta", {})
            dataset_at = metadata.get("lastUpdated") if isinstance(metadata, dict) else None
        elif provider in {"tranco", "umbrella"}:
            ranks = parse_ranked_zip(content, self.config.tranco_limit)
            dataset_at = None
        elif provider == "majestic":
            ranks = parse_majestic(content, self.config.tranco_limit)
            dataset_at = None
        else:
            ranks = parse_crux(content, self.config.tranco_limit)
            dataset_at = None
        return {
            "provider": provider,
            "retrieved_at": now.isoformat(),
            "dataset_at": dataset_at,
            "etag": etag,
            "last_modified": modified,
            "sha256": hashlib.sha256(content).hexdigest(),
            "ranks": ranks,
        }

    def latest(self) -> dict | None:
        try:
            pointer = (self.directory / "latest").read_text(encoding="ascii").strip()
            return self.replay(self.directory / pointer)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @staticmethod
    def replay(path: Path) -> dict:
        data = json.loads(path.read_bytes())
        digest = data.pop("snapshot_hash")
        if data.get("version") != 1 or hashlib.sha256(_canonical(data)).hexdigest() != digest:
            raise ValueError("Invalid trend snapshot")
        data["snapshot_hash"] = digest
        return data

    async def refresh(
        self, now: datetime | None = None, client: httpx.AsyncClient | None = None
    ) -> dict | None:
        now = now or datetime.now(UTC)
        providers = {"tranco": TRANCO_URL}
        if self.config.umbrella_enabled:
            providers["umbrella"] = UMBRELLA_URL
        if self.config.majestic_enabled:
            providers["majestic"] = MAJESTIC_URL
        if self.config.crux_url:
            providers["crux"] = str(self.config.crux_url)
        if os.environ.get("QUIET_CHAOS_RADAR_TOKEN", "").strip():
            providers["radar"] = RADAR_URL
        if client is None:
            async with httpx.AsyncClient(
                transport=SafetyTransport(self.policy), trust_env=False, timeout=30
            ) as owned_client:
                return await self._refresh_with_client(owned_client, providers, now)
        return await self._refresh_with_client(client, providers, now)

    async def _refresh_with_client(
        self, client: httpx.AsyncClient, providers: dict[str, str], now: datetime
    ) -> dict | None:
        changed = False
        failed = False
        for provider, url in providers.items():
            if not self._claim(provider, now):
                continue
            try:
                observation = await self._fetch(client, provider, url, now)
                self._save_observation(observation)
                changed = True
                LOGGER.info("trend source refreshed", extra={"qc_provider": provider})
            except (
                httpx.HTTPError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                zipfile.BadZipFile,
            ) as error:
                failed = True
                LOGGER.warning(
                    "trend source refresh failed",
                    extra={"qc_provider": provider, "qc_error": type(error).__name__},
                )
        previous = self.latest()
        if (failed and previous is not None) or (not changed and previous is not None):
            return previous
        try:
            snapshot = self._rank(providers, now)
            content = _canonical(snapshot)
            name = (
                f"snapshot-{now.strftime('%Y-%m-%dT%H-%M-%S-%fZ')}-{snapshot['snapshot_hash']}.json"
            )
            _atomic_write(self.directory / name, content)
            _atomic_write(self.directory / "latest", name.encode("ascii"))
            return snapshot
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as error:
            LOGGER.warning("trend ranking failed", extra={"qc_error": type(error).__name__})
            return previous

    def _rank(self, providers: dict[str, str], now: datetime) -> dict:
        observations = {name: self._observations(name) for name in providers}
        latest = {name: entries[-1] for name, entries in observations.items() if entries}
        if not latest:
            raise ValueError("No trend observations")
        ranks = {name: normalize_ranks(item["ranks"], self.policy) for name, item in latest.items()}
        rejected = []
        for name, item in latest.items():
            for raw in item["ranks"]:
                domain = registrable_domain(raw)
                original = raw if "://" in raw else f"https://{raw}/"
                if (
                    domain is None
                    or not self.policy.is_allowed_url(original)
                    or not self.policy.is_allowed_url(f"https://{domain}/")
                ):
                    rejected.append(
                        {
                            "provider": name,
                            "input_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                            "decision": "invalid_or_blocked_domain",
                        }
                    )
        history: dict[str, list[dict[str, int]]] = {}
        for name in ("radar", "tranco", "umbrella"):
            entries = observations.get(name, [])
            history[name] = []
            for days in (7, 28):
                eligible = [
                    entry
                    for entry in entries
                    if timedelta(days=days)
                    <= now - datetime.fromisoformat(entry["retrieved_at"])
                    <= timedelta(days=self.config.lookback_days + 1)
                ]
                if eligible:
                    history[name].append(normalize_ranks(eligible[-1]["ranks"], self.policy))
        domains = set().union(
            *(set(ranks.get(name, {})) for name in ("radar", "tranco", "umbrella"))
        )
        candidates = []
        for domain in sorted(domains):
            current = {name: values[domain] for name, values in ranks.items() if domain in values}
            improvements = []
            for name in ("radar", "tranco", "umbrella"):
                if name in current:
                    improvements.extend(
                        (
                            2 if name == "radar" else 1,
                            max(0.0, min(1.0, (old[domain] - current[name]) / old[domain])),
                        )
                        for old in history[name]
                        if domain in old
                    )
            terms = [(0.1, min(len(current) / 3, 1.0))]
            momentum = None
            if improvements:
                momentum = sum(weight * value for weight, value in improvements) / sum(
                    weight for weight, _ in improvements
                )
                terms.append((0.6, momentum))
            if "tranco" in current:
                terms.append(
                    (0.3, max(0.0, 1 - (current["tranco"] - 1) / (self.config.tranco_limit - 1)))
                )
            score = sum(weight * value for weight, value in terms) / sum(
                weight for weight, _ in terms
            )
            candidates.append(
                {
                    "domain": domain,
                    "ranks": current,
                    "score": score,
                    "momentum": momentum,
                    "categories": self.config.categories.get(domain, []),
                    "decision": candidate_decision(domain, self.config, self.policy),
                }
            )
        snapshot = {
            "version": 1,
            "created_at": now.isoformat(),
            "sources": latest,
            "candidates": candidates,
            "rejected": rejected,
        }
        snapshot["snapshot_hash"] = hashlib.sha256(_canonical(snapshot)).hexdigest()
        return snapshot

    def pool(self, snapshot: dict, day: date) -> list[str]:
        scores = {
            candidate["domain"]: candidate["score"]
            for candidate in snapshot["candidates"]
            if candidate["decision"] == "accepted"
            and registrable_domain(candidate["domain"]) == candidate["domain"]
            and candidate_decision(candidate["domain"], self.config, self.policy) == "accepted"
        }
        return [
            f"https://{domain}/"
            for domain in select_daily(
                scores, snapshot["snapshot_hash"], day, self.config.pool_size
            )
        ]


def retry_after(value: str | None, now: datetime) -> datetime:
    from email.utils import parsedate_to_datetime

    if value:
        try:
            return now + timedelta(seconds=max(0, int(value)))
        except OverflowError:
            return datetime.max.replace(tzinfo=UTC)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is not None:
                    return max(now, parsed.astimezone(UTC))
            except (TypeError, ValueError, OverflowError):
                pass
    return now + timedelta(hours=1)
