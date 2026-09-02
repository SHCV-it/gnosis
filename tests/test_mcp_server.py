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
    # hashes must be REAL, bound to the returned content/bytes (not any 64-char string)
    import hashlib
    assert result["content_hash"] == hashlib.sha256(result["markdown"].encode("utf-8")).hexdigest()
    assert result["bytes_sha256"] == hashlib.sha256(PAGE).hexdigest()
    assert result["fetched_at"].endswith("Z")


def test_default_settings_block_private_network(server):
    """Regression (reviewer P0): with default settings, an internal literal must
    be blocked by the SSRF guard — the MCP tool must not probe private nets."""
    from gnosis.core.network import PrivateNetworkBlocked
    settings = Settings()  # allow_private_network defaults to False
    with pytest.raises(PrivateNetworkBlocked):
        asyncio.run(fetch_and_convert(server, settings))


def test_main_fails_cleanly_without_mcp(monkeypatch):
    """mcp must be lazy: main() raises a clean SystemExit when it is absent."""
    import builtins

    from gnosis.mcp_server import main

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("no mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as exc:
        main()
    assert "mcp" in str(exc.value)
