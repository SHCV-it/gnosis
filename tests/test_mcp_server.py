"""Tests for the MCP server's fetch_and_convert tool (core logic, no mcp SDK)."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.config.settings import Settings
from gnosis.mcp_server import fetch_and_convert

PORT = 8948

PAGE = (
    b"<html><head><title>MCP Fixture</title></head><body><main>"
    b"<h1>MCP Fixture Page</h1><p>Substantial content for the MCP server test, "
    b"long enough to exceed the minimum content threshold in the converter so "
    b"the page is captured as content rather than boilerplate.</p></main></body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{PORT}/page"
    srv.shutdown()


def test_fetch_and_convert_returns_provenance(server):
    settings = Settings()
    settings.downloader.allow_private_network = True
    settings.downloader.respect_robots = False
    result = asyncio.run(fetch_and_convert(server, settings))

    assert result["url"] == server
    assert result["status_code"] == 200
    assert "MCP Fixture Page" in result["markdown"]
    assert len(result["content_hash"]) == 64
    assert len(result["bytes_sha256"]) == 64
    assert result["fetched_at"].endswith("Z")
