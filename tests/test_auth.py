"""Tests for downloader auth and header handling (localhost echo server)."""

import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.config.settings import AuthSettings, DownloaderSettings, expand_env
from gnosis.core.downloader import Downloader

ECHO_PORT = 8941


class _EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {
                "authorization": self.headers.get("Authorization"),
                "x_custom": self.headers.get("X-Custom-Auth"),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def echo_server():
    server = HTTPServer(("127.0.0.1", ECHO_PORT), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{ECHO_PORT}/check"
    server.shutdown()


def fetch_headers(settings: DownloaderSettings, url: str) -> dict:
    async def _run():
        async with Downloader(settings) as dl:
            result = await dl.fetch_result(url)
            return json.loads(result.html)

    return asyncio.run(_run())


class TestAuthSchemes:
    def test_bearer(self, echo_server):
        settings = DownloaderSettings(
            rate_limit_ms=0, auth=AuthSettings(type="bearer", token="tok-123")
        )
        received = fetch_headers(settings, echo_server)
        assert received["authorization"] == "Bearer tok-123"

    def test_basic_confluence_pat_pattern(self, echo_server):
        """Confluence Cloud PAT = Basic base64(email:api_token)."""
        settings = DownloaderSettings(
            rate_limit_ms=0,
            auth=AuthSettings(type="basic", username="me@example.com", password="PAT"),
        )
        received = fetch_headers(settings, echo_server)
        expected = base64.b64encode(b"me@example.com:PAT").decode()
        assert received["authorization"] == f"Basic {expected}"

    def test_custom_header(self, echo_server):
        settings = DownloaderSettings(
            rate_limit_ms=0,
            auth=AuthSettings(type="header", name="X-Custom-Auth", value="v1"),
        )
        received = fetch_headers(settings, echo_server)
        assert received["x_custom"] == "v1"

    def test_no_auth_sends_nothing(self, echo_server):
        received = fetch_headers(DownloaderSettings(rate_limit_ms=0), echo_server)
        assert received["authorization"] is None
        assert received["x_custom"] is None

    def test_custom_headers_merge_with_auth(self, echo_server):
        settings = DownloaderSettings(
            rate_limit_ms=0,
            headers={"X-Custom-Auth": "from-headers"},
            auth=AuthSettings(type="bearer", token="t"),
        )
        received = fetch_headers(settings, echo_server)
        assert received["authorization"] == "Bearer t"
        assert received["x_custom"] == "from-headers"


class TestFetchResultProvenance:
    def test_fetch_result_fields(self, echo_server):
        async def _run():
            async with Downloader(DownloaderSettings(rate_limit_ms=0)) as dl:
                return await dl.fetch_result(echo_server)

        result = asyncio.run(_run())
        assert result.status_code == 200
        assert result.final_url == echo_server
        assert result.fetched_at.endswith("Z")
        assert "content-type" in result.response_headers
        assert result.content_type == "application/json"
        assert result.raw_bytes == result.html.encode("utf-8")
        assert result.redirect_chain == [echo_server]


class TestEnvExpansion:
    def test_expands_set_var(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_TEST_TOKEN", "abc")
        assert expand_env("Bearer ${GNOSIS_TEST_TOKEN}") == "Bearer abc"

    def test_missing_var_expands_empty(self, monkeypatch):
        monkeypatch.delenv("GNOSIS_MISSING_VAR", raising=False)
        assert expand_env("x${GNOSIS_MISSING_VAR}y") == "xy"

    def test_nested_structures(self, monkeypatch):
        monkeypatch.setenv("GNOSIS_T", "1")
        assert expand_env({"a": ["${GNOSIS_T}"]}) == {"a": ["1"]}
