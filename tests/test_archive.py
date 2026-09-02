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


def _records(path):
    with open(path, "rb") as f:
        return list(ArchiveIterator(f))


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
    archiver = Archiver(tmp_path, user_agent="gnosis-test/1.0")
    archiver.archive(fetch, bs)
    archiver.close()
    warc_path = tmp_path / "archive.warc.gz"
    assert warc_path.exists()
    records = []
    with open(warc_path, "rb") as f:
        for r in ArchiveIterator(f):
            records.append((r.rec_type, r.rec_headers, r.http_headers, r.content_stream().read()))
    types = [x[0] for x in records]
    assert types == ["warcinfo", "request", "response"]

    # warcinfo record carries software + format metadata
    _, info_headers, info_http, _ = records[0]
    assert info_http is None
    assert info_headers.get_header("WARC-Type") == "warcinfo"

    # request record: method + target URI + request headers
    _, req_headers, req_http, _ = records[1]
    assert req_headers.get_header("WARC-Target-URI") == "http://example.com/page"
    assert req_http.statusline == "GET /page HTTP/1.1"
    assert req_http.get_header("User-Agent") == "gnosis-test/1.0"
    assert req_http.get_header("Host") == "example.com"

    # response record: status line + payload
    _, resp_headers, resp_http, resp_payload = records[2]
    assert resp_headers.get_header("WARC-Target-URI") == "http://example.com/page"
    assert resp_http.statusline == "200 OK"
    assert resp_http.get_header("Content-Length") == str(len(RAW))
    assert resp_http.get_header("Content-Encoding") is None
    assert resp_http.get_header("Transfer-Encoding") is None
    assert resp_payload == RAW


def test_warcinfo_written_once_per_file(tmp_path):
    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    a1 = Archiver(tmp_path)
    a1.archive(fetch, bs)
    a1.close()
    # reopening the same file (append) must NOT add a second warcinfo
    a2 = Archiver(tmp_path)
    a2.archive(fetch, bs)
    a2.close()
    types = [r.rec_type for r in _records(tmp_path / "archive.warc.gz")]
    assert types == ["warcinfo", "request", "response", "request", "response"]


def test_warc_is_valid_gzip(tmp_path):
    import gzip

    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    archiver = Archiver(tmp_path)
    archiver.archive(fetch, bs)
    archiver.close()
    with gzip.open(tmp_path / "archive.warc.gz", "rb") as f:
        assert f.read()


def test_dedup_same_bytes(tmp_path):
    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    archiver = Archiver(tmp_path)
    archiver.archive(fetch, bs)
    archiver.archive(fetch, bs)
    archiver.close()

    assert len(list((tmp_path / ".gnosis-store").iterdir())) == 1
    types = [r.rec_type for r in _records(tmp_path / "archive.warc.gz")]
    # one warcinfo, two request/response pairs (blob deduped, WARC not)
    assert types == ["warcinfo", "request", "response", "request", "response"]


def test_warc_appends_across_reopen(tmp_path):
    fetch = make_fetch()
    bs = compute_bytes_hash(fetch.raw_bytes)
    a1 = Archiver(tmp_path)
    a1.archive(fetch, bs)
    a1.close()
    a2 = Archiver(tmp_path)
    a2.archive(fetch, bs)
    a2.close()
    types = [r.rec_type for r in _records(tmp_path / "archive.warc.gz")]
    assert types == ["warcinfo", "request", "response", "request", "response"]
