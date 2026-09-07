"""Coverage tests for CLI helper functions and error paths not exercised by test_cli.py."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.cli.main import (
    _apply_cli_auth,
    _discover_sitemap,
    _parse_frontmatter_extras,
    _read_md_body,
    _write_failed_data_card,
    download_and_convert,
    url_to_collection_name,
)
from gnosis.config.settings import Settings

PORT = 8959


class TestUrlToCollectionName:
    def test_domain_only(self):
        assert url_to_collection_name("https://docs.example.com/") == "docs-example-com"

    def test_domain_with_path(self):
        assert url_to_collection_name("https://docs.example.com/api/v2") == "docs-example-com-api-v2"

    def test_uppercase_and_special_chars(self):
        assert url_to_collection_name("https://Example.COM/a_b c") == "example-com-a-b-c"


class TestParseFrontmatterExtras:
    def test_valid_pairs_typed(self):
        extras = _parse_frontmatter_extras(("tags: [a, b]", "draft: true", "count: 3"))
        assert extras == {"tags": ["a", "b"], "draft": True, "count": 3}

    def test_no_colon_exits(self):
        with pytest.raises(SystemExit):
            _parse_frontmatter_extras(("notacolon",))

    def test_empty_key_exits(self):
        with pytest.raises(SystemExit):
            _parse_frontmatter_extras((": value",))

    def test_yaml_error_falls_back_to_raw(self):
        extras = _parse_frontmatter_extras(("weird: [unclosed",))
        assert extras == {"weird": "[unclosed"}


class TestApplyCliAuth:
    def test_bearer_token(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "secret-bearer")
        s = Settings()
        _apply_cli_auth(s, extra_headers=(), bearer_token_env="MY_TOKEN", basic_user=None, basic_token_env=None)
        assert s.downloader.auth.type == "bearer"
        assert s.downloader.auth.token == "secret-bearer"

    def test_bearer_missing_env_exits(self):
        s = Settings()
        with pytest.raises(SystemExit):
            _apply_cli_auth(
                s, extra_headers=(), bearer_token_env="UNSET_VAR_XYZ", basic_user=None, basic_token_env=None
            )

    def test_basic_auth(self, monkeypatch):
        monkeypatch.setenv("PW", "hunter2")
        s = Settings()
        _apply_cli_auth(s, extra_headers=(), bearer_token_env=None, basic_user="alice", basic_token_env="PW")
        assert s.downloader.auth.type == "basic"
        assert s.downloader.auth.username == "alice"
        assert s.downloader.auth.password == "hunter2"

    def test_basic_missing_user_exits(self, monkeypatch):
        monkeypatch.setenv("PW", "hunter2")
        s = Settings()
        with pytest.raises(SystemExit):
            _apply_cli_auth(s, extra_headers=(), bearer_token_env=None, basic_user=None, basic_token_env="PW")

    def test_extra_headers_with_env_expansion(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "k-123")
        s = Settings()
        _apply_cli_auth(
            s,
            extra_headers=("X-API-Key: ${API_KEY}",),
            bearer_token_env=None,
            basic_user=None,
            basic_token_env=None,
        )
        assert s.downloader.headers["X-API-Key"] == "k-123"

    def test_invalid_header_exits(self):
        s = Settings()
        with pytest.raises(SystemExit):
            _apply_cli_auth(
                s, extra_headers=("no-colon-here",), bearer_token_env=None, basic_user=None, basic_token_env=None
            )


class TestReadMdBody:
    def test_strips_frontmatter(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("---\ntitle: X\n---\n\n# Body\n\nText")
        assert _read_md_body(p) == "# Body\n\nText"

    def test_no_frontmatter_returns_whole(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("# Just body\n")
        assert _read_md_body(p) == "# Just body\n"

    def test_fence_must_be_column_zero(self, tmp_path):
        # A '---' inside a URL (indented or within a value) must not close the block.
        p = tmp_path / "a.md"
        p.write_text("---\ntitle: X\nurl: https://example.com/a---b\n---\n\nBody")
        assert _read_md_body(p).strip() == "Body"


class TestFailedDataCard:
    def test_writes_failed_data_card(self, tmp_path):
        s = Settings()
        s.output.directory = str(tmp_path)
        _write_failed_data_card(s, "https://example.com/", "boom", policy_decision="deny")
        card = json.loads((tmp_path / "data-card.json").read_text())
        assert card["pages"][0]["error"] == "boom"
        assert card["pages"][0]["policy_decision"] == "deny"


class _SitemapHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/sitemap.xml":
            body = (
                b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                b"<url><loc>http://example.test/a</loc></url>"
                b"<url><loc>http://example.test/b</loc></url>"
                b"</urlset>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
        else:
            body = b"<html><body><main>page</main></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def sitemap_server():
    srv = HTTPServer(("127.0.0.1", PORT), _SitemapHandler)
    srv.allow_reuse_address = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{PORT}"
    srv.shutdown()
    srv.server_close()


def test_discover_sitemap(sitemap_server):
    s = Settings()
    s.downloader.allow_private_network = True
    urls = asyncio.run(_discover_sitemap(f"{sitemap_server}/sitemap.xml", s))
    assert "http://example.test/a" in urls
    assert "http://example.test/b" in urls


def test_download_and_convert_ssrf_block_writes_failed_card(tmp_path):
    s = Settings()
    s.output.directory = str(tmp_path)
    s.downloader.respect_robots = False
    # Default SSRF guard blocks loopback; the error must be recorded, not raised.
    with pytest.raises(SystemExit):
        asyncio.run(download_and_convert("http://127.0.0.1:1/", s, quiet=True, verbose=False))
    card = json.loads((tmp_path / "data-card.json").read_text())
    assert card["pages"][0]["status_code"] is None
    assert "error" in card["pages"][0]
