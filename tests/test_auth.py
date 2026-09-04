"""Tests for downloader auth and header handling (localhost echo server)."""

import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.config.settings import AuthSettings, DownloaderSettings, expand_env
from gnosis.core.downloader import Downloader, RobotsDisallowed

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
    server.allow_reuse_address = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{ECHO_PORT}/check"
    server.shutdown()
    server.server_close()


def fetch_headers(settings: DownloaderSettings, url: str) -> dict:
    async def _run():
        async with Downloader(settings) as dl:
            result = await dl.fetch_result(url)
            return json.loads(result.html)

    return asyncio.run(_run())


class TestAuthSchemes:
    def test_bearer(self, echo_server):
        settings = DownloaderSettings(
            rate_limit_ms=0, allow_private_network=True, auth=AuthSettings(type="bearer", token="tok-123")
        )
        received = fetch_headers(settings, echo_server)
        assert received["authorization"] == "Bearer tok-123"

    def test_basic_confluence_pat_pattern(self, echo_server):
        """Confluence Cloud PAT = Basic base64(email:api_token)."""
        settings = DownloaderSettings(
            rate_limit_ms=0, allow_private_network=True,
            auth=AuthSettings(type="basic", username="me@example.com", password="PAT"),
        )
        received = fetch_headers(settings, echo_server)
        expected = base64.b64encode(b"me@example.com:PAT").decode()
        assert received["authorization"] == f"Basic {expected}"

    def test_custom_header(self, echo_server):
        settings = DownloaderSettings(
            rate_limit_ms=0, allow_private_network=True,
            auth=AuthSettings(type="header", name="X-Custom-Auth", value="v1"),
        )
        received = fetch_headers(settings, echo_server)
        assert received["x_custom"] == "v1"

    def test_no_auth_sends_nothing(self, echo_server):
        received = fetch_headers(DownloaderSettings(rate_limit_ms=0, allow_private_network=True), echo_server)
        assert received["authorization"] is None
        assert received["x_custom"] is None

    def test_custom_headers_merge_with_auth(self, echo_server):
        settings = DownloaderSettings(
            rate_limit_ms=0, allow_private_network=True,
            headers={"X-Custom-Auth": "from-headers"},
            auth=AuthSettings(type="bearer", token="t"),
        )
        received = fetch_headers(settings, echo_server)
        assert received["authorization"] == "Bearer t"
        assert received["x_custom"] == "from-headers"


class TestFetchResultProvenance:
    def test_fetch_result_fields(self, echo_server):
        async def _run():
            async with Downloader(DownloaderSettings(rate_limit_ms=0, allow_private_network=True)) as dl:
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


def test_rate_limit_enforced_across_paths(echo_server):
    """Regression: rate limit must fire between DIFFERENT URLs on the same host
    (previously keyed on the full URL, so it never fired)."""
    import time

    async def _run():
        settings = DownloaderSettings(
            rate_limit_ms=200, retries=0, allow_private_network=True, respect_robots=False
        )
        t0 = time.perf_counter()
        async with Downloader(settings) as dl:
            await dl.fetch_result(echo_server + "/a")
            await dl.fetch_result(echo_server + "/b")
            await dl.fetch_result(echo_server + "/c")
        return time.perf_counter() - t0

    elapsed = asyncio.run(_run())
    assert elapsed >= 0.4, f"rate limit not enforced across paths: {elapsed:.3f}s"


def test_rate_limit_per_host_not_global():
    """Regression: a slow host's sleep must not stall a different host
    (previously the sleep happened while holding a single global lock)."""
    import time

    async def _run():
        settings = DownloaderSettings(
            rate_limit_ms=0, retries=0, allow_private_network=True, respect_robots=False
        )
        dl = Downloader(settings)
        dl.settings.rate_limit_ms = 1000
        # seed the timestamp for host A so its next request must wait
        await dl._rate_limit("http://a.example/first")

        results = {}

        async def timed(key, url):
            t = time.perf_counter()
            await dl._rate_limit(url)
            results[key] = time.perf_counter() - t

        await asyncio.gather(
            timed("a", "http://a.example/second"),
            timed("b", "http://b.example/second"),
        )
        await dl.close()
        return results

    r = asyncio.run(_run())
    assert r["a"] >= 0.8, f"host A did not wait: {r['a']:.3f}s"
    assert r["b"] < 0.5, f"host B was stalled by host A's sleep: {r['b']:.3f}s"


def test_custom_header_not_leaked_to_cross_origin_redirect(echo_server):
    """Regression (#40): auth/custom headers must not be replayed to a
    cross-origin redirect target."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    target = echo_server  # http://127.0.0.1:8941/check

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8951), RedirectHandler)
    srv.allow_reuse_address = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        settings = DownloaderSettings(
            rate_limit_ms=0, retries=0, allow_private_network=True,
            auth=AuthSettings(type="header", name="X-Custom-Auth", value="SECRET"),
        )

        async def _run():
            async with Downloader(settings) as dl:
                return await dl.fetch_result("http://127.0.0.1:8951/start")

        result = asyncio.run(_run())
        body = json.loads(result.html)
        assert body["x_custom"] is None, "custom auth header leaked to redirect target"
        assert body["authorization"] is None
    finally:
        srv.shutdown()
        srv.server_close()


def test_redirect_hop_robots_enforced(echo_server):
    """Regression (#41): each redirect hop must consult the target origin's
    robots.txt, not just the initial URL."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:8952/page")
            self.end_headers()

        def log_message(self, *a):
            pass

    class DisallowHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/robots.txt":
                body = b"User-agent: *\nDisallow: /\n"
            else:
                body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    a = HTTPServer(("127.0.0.1", 8951), RedirectHandler)
    a.allow_reuse_address = True
    b = HTTPServer(("127.0.0.1", 8952), DisallowHandler)
    b.allow_reuse_address = True
    for s in (a, b):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        settings = DownloaderSettings(
            rate_limit_ms=0, retries=0, allow_private_network=True, respect_robots=True
        )

        async def _run():
            async with Downloader(settings) as dl:
                return await dl.fetch_result("http://127.0.0.1:8951/start")

        with pytest.raises(RobotsDisallowed):
            asyncio.run(_run())
    finally:
        a.shutdown()
        a.server_close()
        b.shutdown()
        b.server_close()


def test_same_origin_scheme_sensitive():
    """Regression (P1): origin comparison must include scheme, so an https->http
    downgrade redirect is treated as cross-origin and drops credentials."""
    from gnosis.core.downloader import _same_origin

    assert _same_origin("https://h/p", "http://h/p") is False  # downgrade
    assert _same_origin("http://h/p", "http://H/p") is True    # host case-insensitive
    assert _same_origin("http://h/p", "http://h:80/p") is True  # effective port
    assert _same_origin("http://h/p", "http://h:8080/p") is False


def test_429_retry_after():
    """Regression (#59): a 429 with Retry-After must be retried, not treated as
    a fatal 4xx."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            n = getattr(self.server, "hits", 0)
            self.server.hits = n + 1
            if self.server.hits == 1:
                body = b"slow down"
                self.send_response(429)
                self.send_header("Retry-After", "1")
            else:
                body = b"<html>ok</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8955), H)
    srv.allow_reuse_address = True
    srv.hits = 0
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        async def _run():
            settings = DownloaderSettings(
                rate_limit_ms=0, retries=2, allow_private_network=True, respect_robots=False
            )
            async with Downloader(settings) as dl:
                return await dl.fetch_result("http://127.0.0.1:8955/page")

        result = asyncio.run(_run())
        assert result.status_code == 200
        assert srv.hits == 2
    finally:
        srv.shutdown()
        srv.server_close()


def test_oversized_body_rejected():
    """Regression (#60): a declared oversized body must be rejected before
    buffering."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(60 * 1024 * 1024))  # 60 MiB
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8956), H)
    srv.allow_reuse_address = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        async def _run():
            settings = DownloaderSettings(
                rate_limit_ms=0, retries=0, allow_private_network=True, respect_robots=False
            )
            async with Downloader(settings) as dl:
                return await dl.fetch_result("http://127.0.0.1:8956/page")

        with pytest.raises(Exception):
            asyncio.run(_run())
    finally:
        srv.shutdown()
        srv.server_close()


def test_effective_headers():
    """effective_headers exposes UA + Accept + auth/custom headers for plugins."""
    settings = DownloaderSettings(
        user_agent="UA/1.0",
        headers={"X-Custom": "v"},
        auth=AuthSettings(type="bearer", token="t"),
    )
    dl = Downloader(settings)
    h = dl.effective_headers()
    assert h["User-Agent"] == "UA/1.0"
    assert h["X-Custom"] == "v"
    assert h["Authorization"] == "Bearer t"


def test_304_returns_status_not_error():
    """Regression (judge P0): a 304 must be returned as a FetchResult, not raise."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("If-None-Match") == '"abc"':
                self.send_response(304)
                self.end_headers()
            else:
                body = b"<html>ok</html>"
                self.send_response(200)
                self.send_header("ETag", '"abc"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8959), H)
    srv.allow_reuse_address = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        async def _run():
            settings = DownloaderSettings(
                rate_limit_ms=0, retries=0, allow_private_network=True, respect_robots=False
            )
            async with Downloader(settings) as dl:
                r1 = await dl.fetch_result("http://127.0.0.1:8959/x")
                r2 = await dl.fetch_result(
                    "http://127.0.0.1:8959/x", extra_headers={"If-None-Match": '"abc"'}
                )
                return r1.status_code, r2.status_code

        s1, s2 = asyncio.run(_run())
        assert s1 == 200 and s2 == 304
    finally:
        srv.shutdown()
        srv.server_close()
