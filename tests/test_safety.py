from __future__ import annotations

import socket

import httpx
import pytest

from quiet_chaos.safety import SafetyPolicy, SafetyTransport


def test_safety_policy_allows_http_and_https() -> None:
    policy = SafetyPolicy(["localhost"])

    assert policy.is_allowed_url("https://example.com/path")
    assert policy.is_allowed_url("http://example.com/path")


def test_safety_policy_rejects_unsafe_urls() -> None:
    policy = SafetyPolicy(["localhost", "example.internal"])

    assert not policy.is_allowed_url("file:///etc/passwd")
    assert not policy.is_allowed_url("javascript:alert(1)")
    assert not policy.is_allowed_url("https://localhost/admin")
    assert not policy.is_allowed_url("https://api.example.internal/status")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.2/",
        "http://172.17.0.1/",
        "http://10.1.2.3/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://100.64.0.1/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "http://[fd00::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[ff02::1]/",
        "http://[fe80::1%25eth0]/",
        "http://[broken/",
        "http://example.com:invalid/",
    ],
)
def test_safety_policy_blocks_non_public_addresses(url: str) -> None:
    assert not SafetyPolicy([]).is_allowed_url(url)


def test_safety_policy_allows_public_addresses_and_blocks_trailing_dot() -> None:
    policy = SafetyPolicy(["localhost"])

    assert policy.is_allowed_url("https://8.8.8.8/")
    assert policy.is_allowed_url("https://[2606:4700:4700::1111]/")
    assert not policy.is_allowed_url("http://localhost./")


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.2"], ["::1"], ["fd00::1"], ["93.184.215.14", "10.0.0.1"], []],
)
async def test_transport_blocks_unsafe_dns_results(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str]
) -> None:
    import asyncio

    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    calls = []
    transport = SafetyTransport(
        SafetyPolicy([]), httpx.MockTransport(lambda request: calls.append(request))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.UnsupportedProtocol):
            await client.get("https://example.com/")
    assert calls == []


async def test_transport_pins_dns_and_preserves_host_and_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    transport = SafetyTransport(SafetyPolicy([]), httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://example.com/path?q=1")
    assert str(response.url) == "https://example.com/path?q=1"
    assert str(calls[0].url) == "https://93.184.215.14/path?q=1"
    assert calls[0].headers["host"] == "example.com"
    assert calls[0].extensions["sni_hostname"] == "example.com"


async def test_transport_blocks_redirect_to_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.2/admin"})

    transport = SafetyTransport(SafetyPolicy([]), httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        with pytest.raises(httpx.UnsupportedProtocol):
            await client.get("https://example.com/")
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [(socket.gaierror("no address"), httpx.ConnectError), (TimeoutError(), httpx.ConnectTimeout)],
)
async def test_transport_reports_dns_failures(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: type[httpx.HTTPError]
) -> None:
    import asyncio

    async def resolve(*args, **kwargs):
        raise error

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    transport = SafetyTransport(SafetyPolicy([]), httpx.MockTransport(lambda request: None))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(expected):
            await client.get("https://example.com/")


async def test_transport_blocks_post_and_allows_public_literal() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    transport = SafetyTransport(SafetyPolicy([]), httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.UnsupportedProtocol):
            await client.post("https://8.8.8.8/")
        response = await client.head("https://8.8.8.8/")
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0].method == "HEAD"
