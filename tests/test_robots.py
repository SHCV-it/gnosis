"""Tests for robots.txt honoring and politeness (localhost echo server)."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.config.settings import DownloaderSettings
from gnosis.core.downloader import Downloader, RobotsDisallowed
from gnosis.core.robots import RobotsChecker

ROBOTS_PORT = 8943

ROBOTS_TXT = (
    "User-agent: *\n"
    "Disallow: /blocked\n"
    "Allow: /allowed\n"
    "Crawl-delay: 0.05\n"
)


class _RobotsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/robots.txt":
            body = ROBOTS_TXT.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        elif self.path.startswith("/allowed"):
            body = b"<html><body>allowed</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        elif self.path.startswith("/blocked"):
            body = b"<html><body>blocked</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def robots_server():
    server = HTTPServer(("127.0.0.1", ROBOTS_PORT), _RobotsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{ROBOTS_PORT}"
    server.shutdown()


class _NoRobotsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"not found"
        self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


NO_ROBOTS_PORT = 8944


@pytest.fixture(scope="module")
def no_robots_server():
    server = HTTPServer(("127.0.0.1", NO_ROBOTS_PORT), _NoRobotsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{NO_ROBOTS_PORT}"
    server.shutdown()


class TestRobotsChecker:
    def test_is_allowed(self, robots_server):
        async def _run():
            checker = RobotsChecker("Gnosis/1.1", allow_private_network=True)
            try:
                allowed = await checker.is_allowed(f"{robots_server}/allowed")
                blocked = await checker.is_allowed(f"{robots_server}/blocked")
            finally:
                await checker.close()
            return allowed, blocked

        allowed, blocked = asyncio.run(_run())
        assert allowed is True
        assert blocked is False

    def test_respect_false_bypasses(self, robots_server):
        async def _run():
            checker = RobotsChecker("Gnosis/1.1", allow_private_network=True, respect=False)
            try:
                return await checker.is_allowed(f"{robots_server}/blocked")
            finally:
                await checker.close()

        assert asyncio.run(_run()) is True

    def test_crawl_delay(self, robots_server):
        async def _run():
            checker = RobotsChecker("Gnosis/1.1", allow_private_network=True)
            try:
                return await checker.crawl_delay(f"{robots_server}/allowed")
            finally:
                await checker.close()

        assert asyncio.run(_run()) == 0.05

    def test_fail_open_on_missing_robots(self, no_robots_server):
        async def _run():
            checker = RobotsChecker("Gnosis/1.1", allow_private_network=True)
            try:
                return await checker.is_allowed(f"{no_robots_server}/anything")
            finally:
                await checker.close()

        assert asyncio.run(_run()) is True


class TestDownloaderRobots:
    def test_disallowed_url_raises(self, robots_server):
        async def _run():
            async with Downloader(DownloaderSettings(rate_limit_ms=0, allow_private_network=True)) as dl:
                return await dl.fetch_result(f"{robots_server}/blocked")

        with pytest.raises(RobotsDisallowed):
            asyncio.run(_run())

    def test_allowed_url_succeeds(self, robots_server):
        async def _run():
            async with Downloader(DownloaderSettings(rate_limit_ms=0, allow_private_network=True)) as dl:
                return await dl.fetch_result(f"{robots_server}/allowed")

        result = asyncio.run(_run())
        assert result.status_code == 200

    def test_respect_false_fetches_disallowed(self, robots_server):
        async def _run():
            settings = DownloaderSettings(rate_limit_ms=0, allow_private_network=True, respect_robots=False)
            async with Downloader(settings) as dl:
                return await dl.fetch_result(f"{robots_server}/blocked")

        result = asyncio.run(_run())
        assert result.status_code == 200
