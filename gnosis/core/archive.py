"""WARC archival + content-addressed store for fetched raw bytes.

The content-addressed store writes each unique raw response body once,
keyed by its SHA-256 (`bytes_sha256`), so byte-identical pages are stored
a single time. The WARC (ISO 28500) records full HTTP provenance — a
`warcinfo` header, a `request` record, and a `response` record per fetch —
and is replayable/auditable with standard tooling (warcio, pywb, Common Crawl).
"""

import io
from http.client import responses as _HTTP_REASONS
from pathlib import Path
from urllib.parse import urlparse

from gnosis import __version__
from gnosis.core.downloader import FetchResult

STORE_DIR_NAME = ".gnosis-store"
WARC_FILENAME = "archive.warc.gz"

_WARCINFO = {
    "software": f"gnosis/{__version__}",
    "format": "WARC File Format 1.1",
    "conformsTo": (
        "https://iipc.github.io/warc-specifications/specifications/"
        "warc-format/warc-1.1/"
    ),
}


class Archiver:
    """Persist raw response bytes to a content-addressed store and a WARC."""

    def __init__(
        self,
        output_dir: Path,
        *,
        warc: bool = True,
        user_agent: str = "gnosis",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.warc_enabled = warc
        self.user_agent = user_agent
        self.store_dir = self.output_dir / STORE_DIR_NAME
        self._writer = None
        self._warc_file = None

    def _get_writer(self):
        if self._writer is None and self.warc_enabled:
            from warcio.statusandheaders import StatusAndHeaders
            from warcio.warcwriter import WARCWriter

            self.store_dir.mkdir(parents=True, exist_ok=True)
            self._warc_file = open(str(self.output_dir / WARC_FILENAME), "ab")
            is_new = self._warc_file.tell() == 0
            self._writer = WARCWriter(self._warc_file, gzip=True)
            self._StatusAndHeaders = StatusAndHeaders
            if is_new:
                self._writer.write_record(
                    self._writer.create_warcinfo_record(WARC_FILENAME, _WARCINFO)
                )
        return self._writer

    def archive(self, fetch: FetchResult, bytes_sha256: str) -> str:
        """Archive one fetch; return the content-addressed blob path (relative)."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        blob = self.store_dir / bytes_sha256
        if not blob.exists():
            blob.write_bytes(fetch.raw_bytes)

        if self.warc_enabled:
            writer = self._get_writer()
            self._write_request(writer, fetch)
            self._write_response(writer, fetch)
        return str(blob.relative_to(self.output_dir))

    def _write_request(self, writer, fetch: FetchResult) -> None:
        """Record the outgoing HTTP request that produced this fetch."""
        parsed = urlparse(fetch.url)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        headers = [
            ("Host", parsed.netloc),
            ("User-Agent", self.user_agent),
            ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ]
        http_headers = self._StatusAndHeaders(
            f"GET {path} HTTP/1.1", headers, protocol="HTTP/1.1"
        )
        record = writer.create_warc_record(
            fetch.url, "request", http_headers=http_headers
        )
        writer.write_record(record)

    def _write_response(self, writer, fetch: FetchResult) -> None:
        """Record the HTTP response body + status line."""
        reason = _HTTP_REASONS.get(fetch.status_code, "")
        statusline = f"{fetch.status_code} {reason}".strip()
        excluded = {"content-length", "content-encoding", "transfer-encoding"}
        headers = [
            (k, v) for k, v in fetch.response_headers.items() if k not in excluded
        ]
        headers.append(("Content-Length", str(len(fetch.raw_bytes))))
        http_headers = self._StatusAndHeaders(
            statusline, headers, protocol="HTTP/1.1"
        )
        record = writer.create_warc_record(
            fetch.final_url,
            "response",
            payload=io.BytesIO(fetch.raw_bytes),
            http_headers=http_headers,
        )
        writer.write_record(record)

    def close(self) -> None:
        if self._warc_file is not None:
            try:
                self._warc_file.close()
            except Exception:
                pass
            self._warc_file = None
        self._writer = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
