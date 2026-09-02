"""End-to-end CLI tests against a localhost HTTP server."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import frontmatter
import pytest
from click.testing import CliRunner

from gnosis.cli.main import cli

PORT = 8942

PAGE = b"""<!DOCTYPE html>
<html lang="en"><head><title>Fixture Page</title>
<meta name="author" content="Test Author"></head>
<body>
<nav><p>NAV SHOULD BE STRIPPED</p></nav>
<main>
<h1>Fixture<a class="headerlink" href="#fixture">#</a></h1>
<p>Substantial fixture content for the end to end test of the gnosis CLI.
It needs to be long enough to pass the minimum content threshold check.</p>
<table><thead><tr><th>A</th><th>B</th></tr></thead>
<tbody><tr><td>1</td><td>2</td></tr></tbody></table>
</main>
</body></html>"""

# Page with no real content — body below the 200-char threshold
EMPTY_PAGE = b"""<html><head><title>Near Empty</title></head><body>
<main><p>Hi.</p></main></body></html>"""

# Unicode-heavy page
UNICODE_PAGE = """<html lang="de"><head><title>Überblick — Déjà-vu Füße</title></head>
<body><main><h1>Überblick</h1>
<p>Grüße aus München! Substantial content to pass the threshold check — this
paragraph needs to be long enough with real words and phrases that matter.
Käsefüße und déjà-vu Erfahrungen prägen den Alltag.</p></main></body></html>""".encode()

# Redirect page
REDIRECT_HTML = b"""<html><head><title>Redirect Target</title></head>
<body><main><h1>Landed</h1><p>This is the redirect destination page for testing.
It must have enough content to exceed the minimum threshold check in the
converter. The quick brown fox jumps over the lazy dog repeatedly.</p></main></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/missing":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/empty":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(EMPTY_PAGE)))
            self.end_headers()
            self.wfile.write(EMPTY_PAGE)
            return
        if self.path == "/unicode":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(UNICODE_PAGE)))
            self.end_headers()
            self.wfile.write(UNICODE_PAGE)
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/landed")
            self.end_headers()
            return
        if self.path == "/landed":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(REDIRECT_HTML)))
            self.end_headers()
            self.wfile.write(REDIRECT_HTML)
            return
        if self.path == "/retry":
            # Fail on first two attempts, succeed on third
            retry_attr = "gnosis_retry_count"
            count = getattr(self.server, retry_attr, 0)
            if count < 2:
                setattr(self.server, retry_attr, count + 1)
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(REDIRECT_HTML)))
            self.end_headers()
            self.wfile.write(REDIRECT_HTML)
            return
        if self.path == "/hub":
            body = (
                b'<html><body><main><h1>Hub</h1><p>Substantial hub content for the crawl test, '
                b'long enough to pass the converter and produce useful markdown output.</p>'
                b'<a href="/hub/a">a</a><a href="/hub/b">b</a></main></body></html>'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/hub/a":
            body = (
                b'<html><body><main><h1>Hub A</h1><p>Distinct content for hub page A '
                b'with enough text to convert into markdown output.</p></main></body></html>'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/hub/b":
            body = (
                b'<html><body><main><h1>Hub B</h1><p>Different content for hub page B '
                b'so dedup does not collapse the crawl into fewer files.</p></main></body></html>'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("ETag", '"fixture-etag"')
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
    yield f"http://127.0.0.1:{PORT}"
    srv.shutdown()


def run_cli(args):
    return CliRunner().invoke(cli, [*args, "--allow-private-network"], catch_exceptions=False)


class TestSinglePage:
    def test_writes_frontmatter_and_clean_body(self, server, tmp_path):
        result = run_cli([f"{server}/page", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0, result.output
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1

        parsed = frontmatter.loads(files[0].read_text())
        meta = parsed.metadata
        assert meta["title"] == "Fixture Page"
        assert meta["author"] == "Test Author"
        assert meta["language"] == "en"
        assert meta["url"] == f"{server}/page"
        assert meta["status_code"] == 200
        assert meta["etag"] == '"fixture-etag"'
        assert len(meta["content_hash"]) == 64
        assert meta["fetched_at"].endswith("Z")

        body = parsed.content
        assert body.startswith("# Fixture\n")  # headerlink stripped
        assert "NAV SHOULD BE STRIPPED" not in body
        assert "| A | B |" in body
        assert "| 1 | 2 |" in body

    def test_no_frontmatter_flag(self, server, tmp_path):
        result = run_cli([f"{server}/page", "-o", str(tmp_path), "-f", "-q", "--no-frontmatter"])
        assert result.exit_code == 0
        content = next(tmp_path.glob("*.md")).read_text()
        assert not content.startswith("---")

    def test_frontmatter_extras(self, server, tmp_path):
        result = run_cli(
            [
                f"{server}/page", "-o", str(tmp_path), "-f", "-q",
                "--frontmatter", "tags: [docs, test]",
                "--frontmatter", "owner: kb-team",
            ]
        )
        assert result.exit_code == 0
        meta = frontmatter.loads(next(tmp_path.glob("*.md")).read_text()).metadata
        assert meta["tags"] == ["docs", "test"]
        assert meta["owner"] == "kb-team"

    def test_empty_page_still_written(self, server, tmp_path):
        """Pages with minimal content should still be captured."""
        result = run_cli([f"{server}/empty", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1
        assert "Near Empty" in files[0].read_text()

    def test_unicode_content_preserved(self, server, tmp_path):
        result = run_cli([f"{server}/unicode", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        content = next(tmp_path.glob("*.md")).read_text()
        assert "Überblick" in content
        assert "Käsefüße" in content
        assert "déjà-vu" in content

    def test_redirect_followed(self, server, tmp_path):
        result = run_cli([f"{server}/redirect", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        content = next(tmp_path.glob("*.md")).read_text()
        assert "Redirect Target" in content
        assert "Landed" in content

    def test_retry_succeeds_after_503(self, server, tmp_path):
        """Downloader retries on 5xx errors."""
        result = run_cli([f"{server}/retry", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        assert list(tmp_path.glob("*.md")) != []

    def test_dry_run_exits_zero(self, server):
        result = run_cli([f"{server}/page", "--all", "--dry-run", "-q"])
        assert result.exit_code == 0

    def test_dry_run_without_all_exits_one(self, server):
        result = run_cli([f"{server}/page", "--dry-run", "-q"])
        assert result.exit_code == 1

    def test_verbose_output_includes_detail(self, server, tmp_path):
        result = run_cli([f"{server}/page", "-o", str(tmp_path), "-f", "-v"])
        assert result.exit_code == 0
        # verbose should include sha256 and status
        assert "sha256" in result.output or "status" in result.output

    def test_overwrite_flag(self, server, tmp_path):
        # First run
        run_cli([f"{server}/page", "-o", str(tmp_path), "-f", "-q"])
        # Second run without overwrite — should exit 1
        result = run_cli([f"{server}/page", "-o", str(tmp_path), "-q"])
        assert result.exit_code == 1
        # Third run with overwrite — should succeed
        result = run_cli([f"{server}/page", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0

    def test_manifest_written_for_crawl(self, server, tmp_path):
        result = run_cli([f"{server}/page", "--all", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        import json
        manifest = tmp_path / "_manifest.json"
        assert manifest.exists()
        entries = json.loads(manifest.read_text())
        assert len(entries) >= 1
        assert "content_hash" in entries[0]

    def test_warc_archive_written(self, server, tmp_path):
        result = run_cli([f"{server}/page", "-o", str(tmp_path), "-f", "-q", "--warc"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "archive.warc.gz").exists()
        assert len(list((tmp_path / ".gnosis-store").iterdir())) == 1

    def test_chunk_manifest_written(self, server, tmp_path):
        result = run_cli([f"{server}/page", "-o", str(tmp_path), "-f", "-q", "--chunk"])
        assert result.exit_code == 0, result.output
        assert list(tmp_path.glob("*.chunks.json")) != []

    def test_llms_files_written(self, server, tmp_path):
        result = run_cli([f"{server}/page", "--all", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        assert (tmp_path / "llms.txt").exists()
        assert (tmp_path / "llms-full.txt").exists()

    def test_crawl_writes_checkpoint(self, server, tmp_path):
        result = run_cli([f"{server}/page", "--all", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        assert (tmp_path / ".gnosis-checkpoint.json").exists()


class TestCrawl:
    def test_crawl_writes_manifest(self, server, tmp_path):
        result = run_cli([f"{server}/page", "--all", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        import json
        manifest = tmp_path / "_manifest.json"
        assert manifest.exists()
        entries = json.loads(manifest.read_text())
        assert len(entries) >= 1
        entry = entries[0]
        assert {"url", "file", "content_hash", "fetched_at", "status_code", "title"} <= set(entry)

    def test_crawl_with_concurrency_two(self, server, tmp_path):
        """Concurrent crawl should work without deadlocks."""
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("crawler:\n  concurrent_requests: 2\n  max_pages: 3\n  max_depth: 1")
        result = run_cli(
            [f"{server}/hub", "--all", "-o", str(tmp_path), "-f", "-q", "-c", str(cfg)]
        )
        assert result.exit_code == 0
        assert len(list(tmp_path.glob("*.md"))) >= 3


    def test_resume_rediscovers_pages(self, server, tmp_path):
        cfg1 = tmp_path / "cfg1.yaml"
        cfg1.write_text("crawler:\n  concurrent_requests: 1\n  max_pages: 2\n  max_depth: 1")
        r1 = run_cli([f"{server}/hub", "--all", "-o", str(tmp_path), "-f", "-q", "-c", str(cfg1)])
        assert r1.exit_code == 0
        assert len(list(tmp_path.glob("*.md"))) == 2

        cfg2 = tmp_path / "cfg2.yaml"
        cfg2.write_text("crawler:\n  concurrent_requests: 1\n  max_pages: 3\n  max_depth: 1")
        r2 = run_cli([f"{server}/hub", "--all", "-o", str(tmp_path), "-q", "-c", str(cfg2)])
        assert r2.exit_code == 0
        assert len(list(tmp_path.glob("*.md"))) >= 3
