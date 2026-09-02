"""Tests for llms.txt/llms-full.txt emission + sitemap discovery."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.config.settings import DownloaderSettings
from gnosis.core.downloader import Downloader
from gnosis.core.llms import fetch_sitemap_urls, render_llms_full, render_llms_txt

PORT = 8946

SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://example.com/a</loc></url>
  <url><loc>http://example.com/b</loc></url>
</urlset>"""

MALICIOUS_SITEMAP = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://example.com/x</loc></url>
</urlset>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/robots.txt":
            body = b""
            self.send_response(404)
        elif self.path == "/sitemap.xml":
            body = SITEMAP
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
        elif self.path == "/sitemap-malicious.xml":
            body = MALICIOUS_SITEMAP
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
        else:
            body = b"ok"
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{PORT}"
    srv.shutdown()


PAGES = [
    {"title": "A", "url": "http://x/a", "markdown": "# A\n\ncontent a"},
    {"title": "B", "url": "http://x/b", "markdown": "# B\n\ncontent b"},
]


def test_render_llms_txt():
    txt = render_llms_txt("Site", PAGES)
    assert "# Site" in txt
    assert "- [A](http://x/a)" in txt
    assert "- [B](http://x/b)" in txt


def test_render_llms_full():
    full = render_llms_full(PAGES)
    assert "# A" in full and "content a" in full
    assert "# B" in full and "content b" in full
    assert "---" in full


def test_fetch_sitemap_urls(server):
    async def _run():
        settings = DownloaderSettings(
            rate_limit_ms=0, allow_private_network=True, respect_robots=False
        )
        async with Downloader(settings) as dl:
            return await fetch_sitemap_urls(f"{server}/sitemap.xml", dl)

    urls = asyncio.run(_run())
    assert urls == ["http://example.com/a", "http://example.com/b"]


def test_fetch_sitemap_urls_rejects_entities(server):
    async def _run():
        settings = DownloaderSettings(
            rate_limit_ms=0, allow_private_network=True, respect_robots=False
        )
        async with Downloader(settings) as dl:
            return await fetch_sitemap_urls(f"{server}/sitemap-malicious.xml", dl)

    urls = asyncio.run(_run())
    assert urls == []
