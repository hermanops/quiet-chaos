from __future__ import annotations

import zlib
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

    if response.is_stream_consumed:
        if len(response.content) > max_bytes:
            raise SourceTooLargeError(f"Source response exceeds {max_bytes} bytes")
        return response.content

    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"identity", "gzip", "deflate"}:
        raise httpx.DecodingError(f"Unsupported content encoding: {encoding}")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    prefix = b""
    content = bytearray()
    received = 0
    async for chunk in response.aiter_raw():
        received += len(chunk)
        if received > max_bytes:
            raise SourceTooLargeError(f"Source response exceeds {max_bytes} bytes")
        if encoding == "deflate" and decoder is None:
            prefix += chunk
            if len(prefix) < 2:
                continue
            header = int.from_bytes(prefix[:2], "big")
            wrapped = prefix[0] & 15 == 8 and header % 31 == 0
            decoder = zlib.decompressobj(zlib.MAX_WBITS if wrapped else -zlib.MAX_WBITS)
            chunk, prefix = prefix, b""
        while chunk:
            if decoder is not None:
                try:
                    decoded = decoder.decompress(chunk, max_bytes - len(content) + 1)
                except zlib.error as error:
                    raise httpx.DecodingError("Invalid compressed response") from error
            else:
                decoded = chunk
            if len(content) + len(decoded) > max_bytes:
                raise SourceTooLargeError(f"Source response exceeds {max_bytes} bytes")
            content.extend(decoded)
            if decoder is None or not decoder.unused_data:
                break
            if encoding != "gzip":
                raise httpx.DecodingError("Trailing compressed response data")
            chunk = decoder.unused_data
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    if prefix or (decoder is not None and not decoder.eof):
        raise httpx.DecodingError("Incomplete compressed response")
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
