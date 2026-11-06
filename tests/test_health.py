import asyncio
import json

import httpx
import pytest

from quiet_chaos.health import (
    RuntimeStats,
    check_health,
    health_token_from_env,
    start_health_server,
)


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


async def health_exchange(
    request: bytes,
    *,
    token: str | None = None,
    allowed_hosts: list[str] | None = None,
    fragmented: bool = False,
) -> bytes:
    server = await start_health_server(
        "127.0.0.1", 0, RuntimeStats.start(), token=token, allowed_hosts=allowed_hosts
    )
    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", server.sockets[0].getsockname()[1]
        )
        try:
            if fragmented:
                writer.write(request[:10])
                await writer.drain()
                await asyncio.sleep(0)
                writer.write(request[10:])
            else:
                writer.write(request)
            await writer.drain()
            return await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize(
    ("raw_request", "status"),
    [
        (b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n", 200),
        (b"GET / HTTP/1.0\r\nHost: 127.0.0.1:8080\r\n\r\n", 200),
        (b"GET / HTTP/1.1\r\nHost: [::1]:8080\r\n\r\n", 200),
        (b"GET / HTTP/1.1\r\nHost: LOCALHOST.\r\n\r\n", 200),
        (b"POST / HTTP/1.1\r\nHost: localhost\r\n\r\n", 405),
        (b"PUT / HTTP/1.1\r\nHost: localhost\r\n\r\n", 405),
        (b"GET /missing HTTP/1.1\r\nHost: localhost\r\n\r\n", 404),
        (b"GET / HTTP/2.0\r\nHost: localhost\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: foreign.example\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: user@localhost\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: localhost/path\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: localhost:bad\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: localhost\r\nHost: localhost\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\n\r\n", 400),
        (b"not an HTTP request\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nBad header\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: localhost\r\nX: " + b"x" * 9000 + b"\r\n\r\n", 431),
    ],
)
async def test_health_request_validation(raw_request: bytes, status: int) -> None:
    response = await health_exchange(raw_request)
    assert response.startswith(f"HTTP/1.1 {status} ".encode())
    if status != 200:
        assert b'"stats"' not in response
    if status == 405:
        assert b"allow: GET, HEAD\r\n" in response


async def test_health_head_and_fragmented_requests() -> None:
    response = await health_exchange(b"HEAD / HTTP/1.1\r\nHost: localhost\r\n\r\n", fragmented=True)
    headers, body = response.split(b"\r\n\r\n", 1)
    assert b"200 OK" in headers
    assert b"content-length: 0\r\n" not in headers
    assert body == b""


async def test_health_explicit_proxy_host() -> None:
    response = await health_exchange(
        b"GET / HTTP/1.1\r\nHost: monitor.example:443\r\n\r\n",
        allowed_hosts=["monitor.example"],
    )
    assert response.startswith(b"HTTP/1.1 200 ")


@pytest.mark.parametrize(
    ("authorization", "status"),
    [
        (b"", 401),
        (b"Authorization: Bearer wrong\r\n", 401),
        (b"Authorization: Bearer test-secret\r\n", 200),
        (b"Authorization: Bearer test-secret\r\nAuthorization: Bearer test-secret\r\n", 400),
    ],
)
async def test_health_optional_token(authorization: bytes, status: int) -> None:
    response = await health_exchange(
        b"GET / HTTP/1.1\r\nHost: localhost\r\n" + authorization + b"\r\n",
        token="test-secret",
    )
    assert response.startswith(f"HTTP/1.1 {status} ".encode())
    assert b"test-secret" not in response
    if status == 401:
        assert b"www-authenticate: Bearer" in response
        assert b'"stats"' not in response


@pytest.mark.parametrize("value", ["", " ", "contains space", "line\nbreak", "\x00", "\u00e9"])
def test_health_token_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    if "\x00" in value:
        monkeypatch.setattr("quiet_chaos.health.os.environ", {"QUIET_CHAOS_HEALTH_TOKEN": value})
    else:
        monkeypatch.setenv("QUIET_CHAOS_HEALTH_TOKEN", value)
    with pytest.raises(ValueError, match="nonempty ASCII token"):
        health_token_from_env()


@pytest.mark.parametrize("token", [None, "probe-secret"])
def test_health_probe_uses_optional_token(monkeypatch: pytest.MonkeyPatch, token: str | None):
    if token is None:
        monkeypatch.delenv("QUIET_CHAOS_HEALTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("QUIET_CHAOS_HEALTH_TOKEN", token)
    requests = []

    def open_probe(url, *, headers, timeout, trust_env):
        request = httpx.Request("GET", url, headers=headers)
        requests.append(request)
        assert timeout == 3
        assert trust_env is False
        return httpx.Response(200, request=request)

    monkeypatch.setattr("quiet_chaos.health.httpx.get", open_probe)
    check_health()
    assert requests[0].headers.get("Authorization") == (f"Bearer {token}" if token else None)


async def test_health_incomplete_request_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("quiet_chaos.health._HEADER_TIMEOUT_SECONDS", 0.01)
    assert await health_exchange(b"GET / HTTP/1.1\r\nHost:") == b""


async def test_cli_rejects_empty_token_before_loading_seeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from quiet_chaos.cli import _run

    monkeypatch.setenv("QUIET_CHAOS_HEALTH_TOKEN", "")
    with pytest.raises(ValueError, match="nonempty ASCII token"):
        await _run(None, tmp_path, False, False)
