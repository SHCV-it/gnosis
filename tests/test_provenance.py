"""Tests for provenance frontmatter generation."""

import hashlib

import frontmatter

from gnosis.core.downloader import FetchResult
from gnosis.core.provenance import build_frontmatter, compute_bytes_hash, compute_content_hash, render_document


def make_fetch(**overrides) -> FetchResult:
    base = dict(
        url="https://example.com/docs/page",
        final_url="https://example.com/docs/page",
        status_code=200,
        html="<html></html>",
        fetched_at="2026-08-04T12:00:00Z",
        response_headers={"etag": '"abc123"', "last-modified": "Fri, 31 Jul 2026 16:07:37 GMT"},
    )
    base.update(overrides)
    return FetchResult(**base)


class TestContentHash:
    def test_sha256_of_body(self):
        body = "# Hello\n\nSome content.\n"
        assert compute_content_hash(body) == hashlib.sha256(body.encode()).hexdigest()

    def test_hash_changes_with_content(self):
        assert compute_content_hash("a") != compute_content_hash("b")


class TestBytesHash:
    def test_sha256_of_raw_bytes(self):
        assert compute_bytes_hash(b"hello") == hashlib.sha256(b"hello").hexdigest()

    def test_bytes_hash_independent_of_markdown_hash(self):
        assert compute_bytes_hash(b"<h1>Hello</h1>") != compute_content_hash("# Hello")


class TestFrontmatter:
    def test_core_fields_present(self):
        fm = build_frontmatter(make_fetch(), "# Doc\n")
        assert fm["url"] == "https://example.com/docs/page"
        assert fm["fetched_at"] == "2026-08-04T12:00:00Z"
        assert fm["content_hash"] == compute_content_hash("# Doc\n")
        assert fm["status_code"] == 200
        assert fm["generator"].startswith("gnosis/")
        assert fm["etag"] == '"abc123"'
        assert fm["last_modified"] == "Fri, 31 Jul 2026 16:07:37 GMT"

    def test_metadata_fields_merged(self):
        meta = {"title": "My Page", "language": "en", "author": "Jane", "description": ""}
        fm = build_frontmatter(make_fetch(), "# Doc\n", metadata=meta)
        assert fm["title"] == "My Page"
        assert fm["language"] == "en"
        assert fm["author"] == "Jane"
        assert "description" not in fm  # empty values omitted

    def test_redirect_records_requested_url(self):
        fetch = make_fetch(final_url="https://example.com/docs/page-v2")
        fm = build_frontmatter(fetch, "# Doc\n")
        assert fm["url"] == "https://example.com/docs/page-v2"
        assert fm["requested_url"] == "https://example.com/docs/page"

    def test_extras_cannot_override_core(self):
        fm = build_frontmatter(
            make_fetch(), "# Doc\n", extra={"url": "https://evil.example", "team": "kb"}
        )
        assert fm["url"] == "https://example.com/docs/page"
        assert fm["team"] == "kb"

    def test_rendered_document_parses_with_python_frontmatter(self):
        """Standard YAML frontmatter must round-trip through python-frontmatter
        (the parser used by downstream knowledge pipelines)."""
        fm = build_frontmatter(make_fetch(), "# Doc\n\nBody text.\n", metadata={"title": "T"})
        doc = render_document(fm, "# Doc\n\nBody text.\n")
        parsed = frontmatter.loads(doc)
        assert parsed.metadata["url"] == "https://example.com/docs/page"
        assert parsed.metadata["content_hash"] == fm["content_hash"]
        assert parsed.content.strip().startswith("# Doc")

    def test_rendered_document_shape(self):
        doc = render_document({"title": "X"}, "Body.\n")
        assert doc.startswith("---\n")
        assert "\n---\n" in doc
        assert doc.endswith("Body.\n")

    def test_bytes_sha256_present(self):
        fetch = make_fetch(raw_bytes=b"<html></html>")
        fm = build_frontmatter(fetch, "# Doc")
        assert fm["bytes_sha256"] == compute_bytes_hash(b"<html></html>")

    def test_content_type_and_redirect_chain(self):
        fetch = make_fetch(
            raw_bytes=b"<html></html>",
            content_type="text/html",
            redirect_chain=["https://example.com/a", "https://example.com/b"],
        )
        fm = build_frontmatter(fetch, "# Doc")
        assert fm["content_type"] == "text/html"
        assert fm["redirect_chain"] == ["https://example.com/a", "https://example.com/b"]
