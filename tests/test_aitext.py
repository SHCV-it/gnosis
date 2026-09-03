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
    srv.allow_reuse_address = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{PORT}"
    srv.shutdown()
    srv.server_close()


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


def test_parse_ai_txt_comments_and_empty_values():
    """Regression (reviewer P2): inline # comments stripped, empty values skipped,
    keys lowercased, `allow` directive captured."""
    text = (
        "# full-line comment\n"
        "Training: Allow  # trailing note\n"
        "Data:\n"
        "allow: /api/\n"
        "DISALLOW: /private/\n"
    )
    d = parse_ai_txt(text)
    assert d["training"] == "Allow"
    assert d["allow"] == "/api/"
    assert d["disallow"] == "/private/"
    assert "data" not in d  # empty value skipped


def test_llms_txt_recorded_when_ai_txt_absent():
    """Regression (panel P1): llms.txt must be recorded even when ai.txt is
    absent (previously the ai.txt 404 short-circuited the llms.txt probe)."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/llms.txt":
                body = b"# llms.txt\n"
                self.send_response(200)
            else:
                body = b"not found"
                self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8949), H)

    srv.allow_reuse_address = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        async def _run():
            settings = DownloaderSettings(
                rate_limit_ms=0, retries=0, allow_private_network=True, respect_robots=False
            )
            async with Downloader(settings) as dl:
                return await fetch_host_consent("http://127.0.0.1:8949/page", dl)

        consent = asyncio.run(_run())
        assert consent["llms_txt"] is True
        assert "ai_txt" not in consent
    finally:
        srv.shutdown()
        srv.server_close()
