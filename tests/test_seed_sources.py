import io
import zipfile

from quiet_chaos.seed_sources import SeedStore


def test_parse_tranco_zip() -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("top-1m.csv", "1,example.com\n2,python.org\n")

    urls = SeedStore._parse_tranco_zip(archive_bytes.getvalue(), limit=2)

    assert urls == ["https://example.com/", "https://python.org/"]


def test_normalize_seed_url_defaults_to_https() -> None:
    assert SeedStore._normalize_seed_url("example.com") == "https://example.com/"
    assert SeedStore._normalize_seed_url("http://example.com/news") == "http://example.com/news"
