import asyncio
import json

from quiet_chaos.health import RuntimeStats, start_health_server


async def test_health_response_omits_last_url_and_sets_nosniff() -> None:
    stats = RuntimeStats.start()
    server = await start_health_server("127.0.0.1", 0, stats)
    port = server.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()

    headers, body = response.split(b"\r\n\r\n", 1)
    payload = json.loads(body)

    assert b"200 OK" in headers
    assert b"x-content-type-options: nosniff" in headers.lower()
    assert "last_url" not in payload["stats"]


async def test_health_server_recovers_after_disconnected_client() -> None:
    server = await start_health_server("127.0.0.1", 0, RuntimeStats.start())
    port = server.sockets[0].getsockname()[1]
    try:
        abandoned_reader, abandoned_writer = await asyncio.open_connection("127.0.0.1", port)
        abandoned_writer.close()
        await abandoned_writer.wait_closed()

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()

    assert b"200 OK" in response
