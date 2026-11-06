from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

_MAX_HEADER_BYTES = 8192
_HEADER_TIMEOUT_SECONDS = 5
_STATUS_REASONS = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    431: "Request Header Fields Too Large",
}


@dataclass
class RuntimeStats:
    started_at: str
    requests_attempted: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    response_body_bytes_received: int = 0
    dns_lookups: int = 0
    seeds_loaded: int = 0
    user_agents_loaded: int = 0
    last_error: str | None = None

    @classmethod
    def start(cls) -> RuntimeStats:
        return cls(started_at=datetime.now(UTC).isoformat())


def health_token_from_env() -> str | None:
    token = os.environ.get("QUIET_CHAOS_HEALTH_TOKEN")
    if token is not None and (
        not token or any(not 33 <= ord(character) <= 126 for character in token)
    ):
        message = "QUIET_CHAOS_HEALTH_TOKEN must be a nonempty ASCII token without whitespace"
        raise ValueError(message)
    return token


def check_health() -> None:
    token = health_token_from_env()
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    response = httpx.get("http://127.0.0.1:8080/", headers=headers, timeout=3, trust_env=False)
    response.raise_for_status()


def _host_name(authority: str) -> str:
    if not authority or any(character.isspace() for character in authority):
        raise ValueError("Invalid Host")
    parsed = urlsplit(f"//{authority}")
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid Host")
    _ = parsed.port
    return parsed.hostname.lower().rstrip(".")


def _request_status(raw: bytes, allowed_hosts: set[str], token: str | None) -> tuple[int, bool]:
    try:
        lines = raw.decode("ascii").split("\r\n")
        method, target, version = lines[0].split(" ")
        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            return 400, False
        headers: dict[str, str] = {}
        for line in lines[1:-2]:
            name, value = line.split(":", 1)
            if not name or not all(character.isalnum() or character == "-" for character in name):
                return 400, False
            name = name.lower()
            if name in headers and name in {"host", "authorization", "content-length"}:
                return 400, False
            headers[name] = value.strip()
        if _host_name(headers.get("host", "")) not in allowed_hosts:
            return 400, False
    except (UnicodeError, ValueError):
        return 400, False
    if token is not None and not hmac.compare_digest(
        headers.get("authorization", "").encode("ascii"), f"Bearer {token}".encode("ascii")
    ):
        return 401, method == "HEAD"
    if method not in {"GET", "HEAD"}:
        return 405, False
    if "transfer-encoding" in headers or headers.get("content-length", "0") != "0":
        return 400, method == "HEAD"
    return (200 if target == "/" else 404), method == "HEAD"


def _response_bytes(status: int, head: bool, stats: RuntimeStats) -> bytes:
    payload = {"status": "ok", "stats": asdict(stats)} if status == 200 else {"status": "error"}
    body = json.dumps(payload, sort_keys=True).encode()
    extra_headers = b""
    if status == 405:
        extra_headers = b"allow: GET, HEAD\r\n"
    elif status == 401:
        extra_headers = b'www-authenticate: Bearer realm="health"\r\n'
    return (
        f"HTTP/1.1 {status} {_STATUS_REASONS[status]}\r\n".encode()
        + b"content-type: application/json\r\n"
        + b"x-content-type-options: nosniff\r\n"
        + b"cache-control: no-store\r\n"
        + f"content-length: {len(body)}\r\n".encode()
        + extra_headers
        + b"connection: close\r\n\r\n"
        + (b"" if head else body)
    )


async def start_health_server(
    host: str,
    port: int,
    stats: RuntimeStats,
    *,
    allowed_hosts: list[str] | None = None,
    token: str | None = None,
) -> asyncio.Server:
    hosts = {"localhost", "127.0.0.1", "::1"}
    if host not in {"0.0.0.0", "::"}:
        hosts.add(_host_name(f"[{host}]" if ":" in host else host))
    hosts.update(_host_name(value) for value in (allowed_hosts or []))

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                raw = await asyncio.wait_for(
                    reader.readuntil(b"\r\n\r\n"), timeout=_HEADER_TIMEOUT_SECONDS
                )
                status, head = (
                    _request_status(raw, hosts, token)
                    if len(raw) <= _MAX_HEADER_BYTES
                    else (431, False)
                )
            except (TimeoutError, asyncio.IncompleteReadError):
                return
            except asyncio.LimitOverrunError:
                status, head = 431, False
            writer.write(_response_bytes(status, head, stats))
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()

    return await asyncio.start_server(handle, host, port, limit=_MAX_HEADER_BYTES)
