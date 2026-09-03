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


def test_parse_ai_txt_group_scoping():
    """Regression (panel P2): directives scoped to a specific User-Agent must not
    be flattened away by a later wildcard group."""
    text = (
        "User-Agent: GPTBot\n"
        "Training: Deny\n\n"
        "User-Agent: *\n"
        "Training: Allow\n"
    )
    # gnosis's UA is not GPTBot, so the * group applies -> Allow
    assert parse_ai_txt(text, user_agent="Gnosis/2.0")["training"] == "Allow"
    # GPTBot's specific opt-out must be preserved -> Deny
    assert parse_ai_txt(text, user_agent="GPTBot")["training"] == "Deny"


def test_consent_cache_expires(monkeypatch):
    """Regression (#31): a stale cache entry must be re-fetched, not returned."""
    import gnosis.core.aitext as aitext
    hits = {"ai": 0}

    class Counting(_Handler):
        def do_GET(self):
            if self.path == "/ai.txt":
                hits["ai"] += 1
            super().do_GET()

    from http.server import HTTPServer

    srv = HTTPServer(("127.0.0.1", 8950), Counting)
    srv.allow_reuse_address = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        async def _run():
            settings = DownloaderSettings(
                rate_limit_ms=0, retries=0, allow_private_network=True, respect_robots=False
            )
            async with Downloader(settings) as dl:
                return await aitext.fetch_host_consent("http://127.0.0.1:8950/page", dl)

        first = asyncio.run(_run())
        assert first["ai_txt"]["training"] == "Allow"
        assert hits["ai"] == 1
        # within TTL: cached, no re-fetch
        asyncio.run(_run())
        assert hits["ai"] == 1
        # force expiry: re-fetch
        monkeypatch.setattr(aitext, "_CACHE_TTL_SECONDS", -1.0)
        asyncio.run(_run())
        assert hits["ai"] == 2
    finally:
        srv.shutdown()
        srv.server_close()


def test_parse_ai_txt_ua_prefix_matching():
    """Regression (#46): a User-Agent group token must prefix-match the crawler
    UA (robots.txt semantics), not require exact full-string equality."""
    text = "User-Agent: gnosis\nTraining: Deny\n\nUser-Agent: *\nTraining: Allow\n"
    d = parse_ai_txt(text, user_agent="Gnosis/2.0 (auditable website-to-markdown converter)")
    assert d["training"] == "Deny"

    # a more specific group still wins over a generic one
    text2 = (
        "User-Agent: gnosis\nTraining: Deny\n\n"
        "User-Agent: gnosis/2.0\nTraining: Allow\n"
    )
    d2 = parse_ai_txt(text2, user_agent="Gnosis/2.0 (auditable website-to-markdown converter)")
    assert d2["training"] == "Allow"


def test_parse_ai_txt_token_boundary():
    """Regression (reviewer P2): 'g' must NOT match 'Gnosis/2.0' (token boundary),
    while 'gnosis' and 'gnosis/2.0' must."""
    text = "User-Agent: g\nTraining: Deny\n\nUser-Agent: *\nTraining: Allow\n"
    assert parse_ai_txt(text, user_agent="Gnosis/2.0")["training"] == "Allow"


def test_parse_ai_txt_empty_ua_group_falls_back_to_wildcard():
    """Regression (reviewer P2): an empty User-Agent: line is treated as
    wildcard, so its directives are wildcard-scoped (not a separate empty group
    that shadows or drops them)."""
    text = "User-Agent:\nTraining: Deny\n"
    assert parse_ai_txt(text, user_agent="Gnosis/2.0")["training"] == "Deny"
