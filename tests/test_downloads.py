import gzip
import tracemalloc
import zlib

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


@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate", "raw-deflate"])
async def test_read_response_limited_decodes_at_exact_limit(encoding: str) -> None:
    content = b"hello" * 100
    encoded = content
    if encoding == "gzip":
        encoded = gzip.compress(content)
    elif encoding == "deflate":
        encoded = zlib.compress(content)
    elif encoding == "raw-deflate":
        encoded = zlib.compress(content, wbits=-zlib.MAX_WBITS)

    class EncodedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for byte in encoded:
                yield bytes([byte])

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-encoding": encoding.removeprefix("raw-")},
            stream=EncodedStream(),
        )
    )
    async with (
        httpx.AsyncClient(transport=transport) as client,
        client.stream("GET", "https://example.com/") as response,
    ):
        assert await read_response_limited(response, len(content)) == content


async def test_read_response_limited_bounds_compressed_expansion() -> None:
    encoded = gzip.compress(b"x" * 10_000_000)

    class CompressedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield encoded

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-encoding": "gzip"}, stream=CompressedStream()
        )
    )
    async with (
        httpx.AsyncClient(transport=transport) as client,
        client.stream("GET", "https://example.com/") as response,
    ):
        tracemalloc.start()
        try:
            with pytest.raises(SourceTooLargeError):
                await read_response_limited(response, 64 * 1024)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert peak < 1_000_000


async def test_read_response_limited_rejects_truncated_gzip() -> None:
    class TruncatedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield gzip.compress(b"hello")[:-3]

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"content-encoding": "gzip"}, stream=TruncatedStream()
                )
            )
        ) as client,
        client.stream("GET", "https://example.com/") as response,
    ):
        with pytest.raises(httpx.DecodingError):
            await read_response_limited(response, 1024)
