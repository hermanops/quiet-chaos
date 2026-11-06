from __future__ import annotations

from typing import BinaryIO

import httpx

MAX_SOURCE_BYTES = 32 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024


class SourceTooLargeError(httpx.HTTPError):
    pass


async def read_response_limited(response: httpx.Response, max_bytes: int) -> bytes:
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > max_bytes:
            raise SourceTooLargeError(f"Source response exceeds {max_bytes} bytes")

    content = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=_CHUNK_SIZE):
        if len(content) + len(chunk) > max_bytes:
            raise SourceTooLargeError(f"Source response exceeds {max_bytes} bytes")
        content.extend(chunk)
    return bytes(content)


def read_decompressed_limited(stream: BinaryIO, max_bytes: int) -> bytes:
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    chunks = []
    total = 0
    while True:
        chunk = stream.read(min(_CHUNK_SIZE, max_bytes - total + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise SourceTooLargeError(f"Decompressed source exceeds {max_bytes} bytes")
        chunks.append(chunk)
