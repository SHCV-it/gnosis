"""End-to-end CLI tests against a localhost HTTP server."""

import json
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


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/missing":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
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
    return CliRunner().invoke(cli, args, catch_exceptions=False)


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

    def test_404_exits_1(self, server, tmp_path):
        result = run_cli([f"{server}/missing", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 1
        assert list(tmp_path.glob("*.md")) == []


class TestCrawl:
    def test_crawl_writes_manifest(self, server, tmp_path):
        result = run_cli([f"{server}/", "--all", "-o", str(tmp_path), "-f", "-q"])
        assert result.exit_code == 0
        manifest = tmp_path / "_manifest.json"
        assert manifest.exists()
        entries = json.loads(manifest.read_text())
        assert len(entries) >= 1
        entry = entries[0]
        assert {"url", "file", "content_hash", "fetched_at", "status_code", "title"} <= set(entry)
