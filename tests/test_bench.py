"""Tests for gnosis-bench."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.bench import _emit, _run
from gnosis.config.settings import DownloaderSettings, Settings

PORT = 8945

PAGE = b"""<html><head><title>Bench</title></head><body><main>
<h1>Bench</h1><p>Substantial content for the bench test, long enough to exceed
the minimum content threshold check in the converter pipeline.</p>
</main></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/robots.txt":
            body = b""
            self.send_response(404)
        else:
            body = PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{PORT}"
    srv.shutdown()


def _settings():
    s = Settings()
    s.downloader = DownloaderSettings(
        rate_limit_ms=0, allow_private_network=True, respect_robots=False
    )
    return s


def test_run_bench(server):
    results = asyncio.run(_run([f"{server}/page"], _settings(), 1))
    assert len(results) == 1
    r = results[0]
    assert r["status_code"] == 200
    assert r["markdown_chars"] > 0
    assert r["provenance_complete"] is True


def test_emit_writes_report(tmp_path):
    results = [
        {
            "url": "x",
            "status_code": 200,
            "latency_ms": 10,
            "raw_bytes": 100,
            "markdown_chars": 50,
            "provenance_complete": True,
        }
    ]
    out = tmp_path / "report.json"
    _emit(results, out, ["x"])
    data = json.loads(out.read_text())
    assert data["corpus_size"] == 1
    assert data["successful"] == 1
    assert data["success_rate"] == 1.0
    assert data["provenance_complete"] == 1
