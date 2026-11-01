from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx


class SafetyPolicy:
    def __init__(self, deny_domains: list[str]) -> None:
        self._deny_domains = [domain.lower() for domain in deny_domains]

    def is_allowed_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            _ = parsed.port
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"} or not host:
            return False
        host = host.lower().rstrip(".")
        if "%" in host or any(
            host == denied or host.endswith(f".{denied}") or host.startswith(denied)
            for denied in self._deny_domains
        ):
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return True
        return self.is_public_address(host)

    @staticmethod
    def is_public_address(value: str) -> bool:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return (
            address.is_global
            and not address.is_multicast
            and not address.is_reserved
            and not address.is_unspecified
        )


class SafetyTransport(httpx.AsyncBaseTransport):
    def __init__(
        self, policy: SafetyPolicy, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._policy = policy
        self._transport = transport or httpx.AsyncHTTPTransport(
            limits=httpx.Limits(max_keepalive_connections=0)
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in {"GET", "HEAD"} or not self._policy.is_allowed_url(
            str(request.url)
        ):
            raise httpx.UnsupportedProtocol("Request blocked by safety policy", request=request)
        host = request.url.host
        try:
            ipaddress.ip_address(host)
            address = host
        except ValueError:
            timeout = request.extensions.get("timeout", {}).get("connect")
            try:
                records = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(
                        host,
                        request.url.port or (443 if request.url.scheme == "https" else 80),
                        type=socket.SOCK_STREAM,
                    ),
                    timeout=timeout,
                )
            except TimeoutError as error:
                raise httpx.ConnectTimeout("DNS resolution timed out", request=request) from error
            except OSError as error:
                raise httpx.ConnectError("DNS resolution failed", request=request) from error
            addresses = [record[4][0] for record in records]
            if not addresses or not all(self._policy.is_public_address(item) for item in addresses):
                raise httpx.UnsupportedProtocol(
                    "DNS destination blocked by safety policy", request=request
                ) from None
            address = addresses[0]
        pinned_request = httpx.Request(
            request.method,
            request.url.copy_with(host=address),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        return await self._transport.handle_async_request(pinned_request)

    async def aclose(self) -> None:
        await self._transport.aclose()
