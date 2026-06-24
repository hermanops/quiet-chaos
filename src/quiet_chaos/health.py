from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass
class RuntimeStats:
    started_at: str
    requests_attempted: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    dns_lookups: int = 0
    last_error: str | None = None
    last_url: str | None = None

    @classmethod
    def start(cls) -> RuntimeStats:
        return cls(started_at=datetime.now(UTC).isoformat())


async def start_health_server(host: str, port: int, stats: RuntimeStats) -> asyncio.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(2048)
        body = json.dumps({"status": "ok", "stats": asdict(stats)}, sort_keys=True).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            + b"content-type: application/json\r\n"
            + f"content-length: {len(body)}\r\n".encode()
            + b"connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)
