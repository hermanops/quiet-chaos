from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from quiet_chaos.config import AppConfig, UserAgentSourceConfig
from quiet_chaos.defaults import DEFAULT_USER_AGENTS
from quiet_chaos.downloads import MAX_SOURCE_BYTES, read_response_limited
from quiet_chaos.safety import SafetyPolicy, SafetyTransport


class UserAgentStore:
    def __init__(self, config: AppConfig, cache_dir: Path) -> None:
        self._config = config
        self._cache_dir = cache_dir

    async def load(self, refresh: bool = False) -> list[str]:
        agents = [str(agent) for agent in self._config.user_agents]
        source = self._config.user_agent_source
        if source.enabled:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"accept-encoding": "gzip, deflate"},
                transport=SafetyTransport(SafetyPolicy(self._config.deny_domains)),
                trust_env=False,
                timeout=30,
            ) as client:
                agents.extend(await self._load_source(client, source, refresh))

        unique = list(dict.fromkeys(agent for agent in agents if agent.strip()))
        if not unique:
            unique = DEFAULT_USER_AGENTS.copy()
        random.shuffle(unique)
        return unique

    async def _load_source(
        self,
        client: httpx.AsyncClient,
        source: UserAgentSourceConfig,
        refresh: bool,
    ) -> list[str]:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / f"user-agents-{self._cache_key(str(source.url))}.cache"
        if not refresh and self._is_fresh(cache_file, source.refresh_hours):
            return cache_file.read_text(encoding="utf-8").splitlines()[: source.limit]

        try:
            async with client.stream(
                "GET",
                str(source.url),
                headers={"user-agent": DEFAULT_USER_AGENTS[0]},
            ) as response:
                response.raise_for_status()
                content = await read_response_limited(response, MAX_SOURCE_BYTES)
        except httpx.HTTPError:
            if cache_file.exists():
                return cache_file.read_text(encoding="utf-8").splitlines()[: source.limit]
            return []

        agents = self._parse_useragents_me(
            content.decode(response.encoding or "utf-8", errors="replace"), source.limit
        )
        if agents:
            cache_file.write_text("\n".join(agents), encoding="utf-8")
        return agents

    @staticmethod
    def _parse_useragents_me(text: str, limit: int) -> list[str]:
        if limit <= 0:
            return []
        agents: list[str] = []
        seen: set[str] = set()
        start: int | None = None
        stack: list[str] = []
        quoted = False
        escaped = False
        for index, character in enumerate(text):
            if start is None:
                if character == "[":
                    start = index
                    stack = ["]"]
                    quoted = escaped = False
                continue
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                stack.append("]" if character == "[" else "}")
                if len(stack) > 64:
                    start = None
                    stack.clear()
            elif character in "]}":
                if character != stack.pop():
                    start = None
                    stack.clear()
                elif not stack:
                    agents.extend(
                        _extract_agents_from_json_block(
                            text[start : index + 1], seen, limit - len(agents)
                        )
                    )
                    if len(agents) >= limit:
                        return agents
                    start = None
        return agents

    @staticmethod
    def _is_fresh(path: Path, refresh_hours: int) -> bool:
        if not path.exists():
            return False
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        return datetime.now(UTC) - modified_at < timedelta(hours=refresh_hours)

    @staticmethod
    def _cache_key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _extract_agents_from_json_block(block: str, seen: set[str], limit: int) -> list[str]:
    if limit <= 0:
        return []
    try:
        parsed = json.loads(block)
    except json.JSONDecodeError:
        return []

    agents: list[str] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        user_agent = str(entry.get("ua", "")).strip()
        if user_agent and user_agent not in seen:
            agents.append(user_agent)
            seen.add(user_agent)
            if len(agents) >= limit:
                break
    return agents
