"""WARC archival + content-addressed store for fetched raw bytes.

The content-addressed store writes each unique raw response body once,
keyed by its SHA-256 (`bytes_sha256`), so byte-identical pages are stored
a single time. The WARC (ISO 28500) records full HTTP provenance and is
replayable/auditable with standard tooling (warcio, pywb, Common Crawl).
"""

import io
from http.client import responses as _HTTP_REASONS
from pathlib import Path

from gnosis.core.downloader import FetchResult

STORE_DIR_NAME = ".gnosis-store"
WARC_FILENAME = "archive.warc.gz"


class Archiver:
    """Persist raw response bytes to a content-addressed store and a WARC."""

    def __init__(self, output_dir: Path, *, warc: bool = True) -> None:
        self.output_dir = Path(output_dir)
        self.warc_enabled = warc
        self.store_dir = self.output_dir / STORE_DIR_NAME
        self._writer = None
        self._warc_file = None

    def _get_writer(self):
        if self._writer is None and self.warc_enabled:
            from warcio.statusandheaders import StatusAndHeaders
            from warcio.warcwriter import WARCWriter

            self.store_dir.mkdir(parents=True, exist_ok=True)
            self._warc_file = open(str(self.output_dir / WARC_FILENAME), "ab")
            self._writer = WARCWriter(self._warc_file, gzip=True)
            self._StatusAndHeaders = StatusAndHeaders
        return self._writer

    def archive(self, fetch: FetchResult, bytes_sha256: str) -> str:
        """Archive one fetch; return the content-addressed blob path (relative)."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        blob = self.store_dir / bytes_sha256
        if not blob.exists():
            blob.write_bytes(fetch.raw_bytes)

        if self.warc_enabled:
            writer = self._get_writer()
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

        return str(blob.relative_to(self.output_dir))

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
