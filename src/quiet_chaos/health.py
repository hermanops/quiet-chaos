from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass
class RuntimeStats:
    started_at: str
    requests_attempted: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    dns_lookups: int = 0
    seeds_loaded: int = 0
    user_agents_loaded: int = 0
    last_error: str | None = None

    @classmethod
    def start(cls) -> RuntimeStats:
        return cls(started_at=datetime.now(UTC).isoformat())


async def start_health_server(host: str, port: int, stats: RuntimeStats) -> asyncio.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                await asyncio.wait_for(reader.read(2048), timeout=5)
            except TimeoutError:
                return
            body = json.dumps({"status": "ok", "stats": asdict(stats)}, sort_keys=True).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                + b"content-type: application/json\r\n"
                + b"x-content-type-options: nosniff\r\n"
                + f"content-length: {len(body)}\r\n".encode()
                + b"connection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)
