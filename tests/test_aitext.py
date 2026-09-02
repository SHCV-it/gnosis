"""Tests for ai.txt / llms.txt consent discovery."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.config.settings import DownloaderSettings
from gnosis.core.aitext import fetch_host_consent, parse_ai_txt, summarize_ai_txt
from gnosis.core.downloader import Downloader

PORT = 8947

AI_TXT = """# Example ai.txt
Spawning: https://spawning.ai/
Training: Allow
Data: Allow
User-Agent: *
Disallow: /private/
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ai.txt":
            body = AI_TXT.encode()
            ctype = "text/plain"
        elif self.path == "/llms.txt":
            body = b"# llms.txt\n\n- [Page](/page)\n"
            ctype = "text/plain"
        else:
            body = b"<html>ok</html>"
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
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


def test_parse_ai_txt():
    d = parse_ai_txt(AI_TXT)
    assert d["training"] == "Allow"
    assert d["data"] == "Allow"
    assert d["disallow"] == "/private/"


def test_summarize_ai_txt_keeps_only_relevant_keys():
    out = summarize_ai_txt({"training": "Allow", "data": "Deny", "spawning": "x"})
    assert out == {"training": "Allow", "data": "Deny"}


def test_fetch_host_consent_records_directives(server):
    async def _run():
        settings = DownloaderSettings(
            rate_limit_ms=0, allow_private_network=True, respect_robots=False
        )
        async with Downloader(settings) as dl:
            return await fetch_host_consent(f"{server}/page", dl)

    consent = asyncio.run(_run())
    assert consent["ai_txt"]["training"] == "Allow"
    assert consent["ai_txt"]["data"] == "Allow"
    assert consent["llms_txt"] is True


def test_fetch_host_consent_absent_is_empty(server):
    async def _run():
        settings = DownloaderSettings(
            rate_limit_ms=0, retries=0, allow_private_network=True, respect_robots=False
        )
        # a different host with no consent files -> empty
        async with Downloader(settings) as dl:
            return await fetch_host_consent("http://127.0.0.1:1/none", dl)

    assert asyncio.run(_run()) == {}
