"""Tests for WARC archival + content-addressed store."""

from warcio.archiveiterator import ArchiveIterator

from gnosis.core.archive import Archiver
from gnosis.core.downloader import FetchResult
from gnosis.core.provenance import compute_bytes_hash

RAW = b"<html><body>hello</body></html>"


def make_fetch():
    return FetchResult(
        url="http://example.com/page",
        final_url="http://example.com/page",
        status_code=200,
        html=RAW.decode(),
        fetched_at="2026-01-01T00:00:00Z",
        response_headers={"content-type": "text/html"},
        raw_bytes=RAW,
    )


def test_content_addressed_store(tmp_path):
    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    archiver = Archiver(tmp_path)
    rel = archiver.archive(fetch, bs)
    archiver.close()
    assert rel == f".gnosis-store/{bs}"
    assert (tmp_path / ".gnosis-store" / bs).read_bytes() == RAW


def test_warc_record_written(tmp_path):
    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    archiver = Archiver(tmp_path)
    archiver.archive(fetch, bs)
    archiver.close()
    warc_path = tmp_path / "archive.warc.gz"
    assert warc_path.exists()
    with open(warc_path, "rb") as f:
        records = []
        for r in ArchiveIterator(f):
            records.append(
                (r.rec_type, r.rec_headers.get_header("WARC-Target-URI"), r.http_headers, r.content_stream().read())
            )
    assert len(records) == 1
    rec_type, target, http_headers, payload = records[0]
    assert rec_type == "response"
    assert target == "http://example.com/page"
    assert payload == RAW
    assert http_headers is not None
    assert http_headers.statusline == "200 OK"
    assert http_headers.get_header("Content-Length") == str(len(RAW))
    assert http_headers.get_header("Content-Encoding") is None
    assert http_headers.get_header("Transfer-Encoding") is None

def test_warc_is_valid_gzip(tmp_path):
    import gzip

    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    archiver = Archiver(tmp_path)
    archiver.archive(fetch, bs)
    archiver.close()
    with gzip.open(tmp_path / "archive.warc.gz", "rb") as f:
        assert f.read()  # BadGzipFile if trailer missing/corrupt

def test_dedup_same_bytes(tmp_path):
    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    archiver = Archiver(tmp_path)
    archiver.archive(fetch, bs)
    archiver.archive(fetch, bs)
    archiver.close()
    # one blob (dedup) but two WARC records (one per fetch)
    assert len(list((tmp_path / ".gnosis-store").iterdir())) == 1
    with open(tmp_path / "archive.warc.gz", "rb") as f:
        assert len(list(ArchiveIterator(f))) == 2


def test_warc_appends_across_reopen(tmp_path):
    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    a1 = Archiver(tmp_path)
    a1.archive(fetch, bs)
    a1.close()
    a2 = Archiver(tmp_path)
    a2.archive(fetch, bs)
    a2.close()
    with open(tmp_path / "archive.warc.gz", "rb") as f:
        assert len(list(ArchiveIterator(f))) == 2
