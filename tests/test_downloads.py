import httpx
import pytest

from quiet_chaos.downloads import SourceTooLargeError, read_response_limited


async def _read_limited(client: httpx.AsyncClient) -> bytes:
    async with client.stream("GET", "https://example.com/") as response:
        return await read_response_limited(response, max_bytes=5)


class ChunkedStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"1234"
        yield b"5678"

    async def aclose(self) -> None:
        pass


async def test_read_response_limited_rejects_streamed_oversize() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=ChunkedStream()))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SourceTooLargeError, match="Source response"):
            await _read_limited(client)


async def test_read_response_limited_rejects_oversized_content_length() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-length": "8"},
            stream=ChunkedStream(),
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SourceTooLargeError, match="Source response"):
            await _read_limited(client)
