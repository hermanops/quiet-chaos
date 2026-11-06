import gzip
import io
import zipfile

import pytest

from quiet_chaos.downloads import SourceTooLargeError
from quiet_chaos.seed_sources import SeedStore


def test_parse_tranco_zip() -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("top-1m.csv", "1,example.com\n2,python.org\n")

    urls = SeedStore._parse_tranco_zip(archive_bytes.getvalue(), limit=2)

    assert urls == ["https://example.com/", "https://python.org/"]


def test_parse_crux_gzip_csv() -> None:
    content = gzip.compress(b"rank,origin\n1,https://example.com\n2,python.org\n")

    urls = SeedStore._parse_crux_gzip_csv(content, limit=2)

    assert urls == ["https://example.com", "https://python.org/"]


def test_parse_tranco_zip_rejects_oversized_expanded_content() -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("top-1m.csv", "1,example.com\n" * 10)

    with pytest.raises(SourceTooLargeError, match="Decompressed source"):
        SeedStore._parse_tranco_zip(archive_bytes.getvalue(), limit=1, max_bytes=8)


def test_parse_crux_gzip_csv_rejects_oversized_expanded_content() -> None:
    content = gzip.compress(b"rank,origin\n" + b"1,example.com\n" * 10)

    with pytest.raises(SourceTooLargeError, match="Decompressed source"):
        SeedStore._parse_crux_gzip_csv(content, limit=1, max_bytes=8)


def test_normalize_seed_url_defaults_to_https() -> None:
    assert SeedStore._normalize_seed_url("example.com") == "https://example.com/"
    assert SeedStore._normalize_seed_url("http://example.com/news") == "http://example.com/news"
