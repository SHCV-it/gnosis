"""Tests for the optional JS renderer + render provenance."""

import asyncio

import pytest

from gnosis.core.downloader import FetchResult
from gnosis.core.provenance import build_frontmatter
from gnosis.core.render import ObscuraRenderer, RenderError, RenderResult


class TestRenderResult:
    def test_defaults(self):
        r = RenderResult(html="<html></html>")
        assert r.engine == ""
        assert r.version == ""
        assert r.js_executed is True


class TestObscuraRenderer:
    def test_missing_binary_raises(self):
        renderer = ObscuraRenderer(binary="definitely-not-a-real-binary-xyz")
        with pytest.raises(RenderError):
            asyncio.run(renderer.render("http://example.com/"))


def _fetch(**overrides):
    base = dict(
        url="http://example.com/",
        final_url="http://example.com/",
        status_code=200,
        html="<html></html>",
        fetched_at="2026-01-01T00:00:00Z",
        raw_bytes=b"<html></html>",
    )
    base.update(overrides)
    return FetchResult(**base)


class TestRenderProvenance:
    def test_render_fields_recorded(self):
        fetch = _fetch(
            render_engine="obscura",
            render_version="1.2.3",
            render_timestamp="2026-01-01T00:00:00Z",
            js_executed=True,
        )
        fm = build_frontmatter(fetch, "# Doc")
        assert fm["render_engine"] == "obscura"
        assert fm["render_version"] == "1.2.3"
        assert fm["render_timestamp"] == "2026-01-01T00:00:00Z"
        assert fm["js_executed"] is True

    def test_no_render_fields_when_static(self):
        fm = build_frontmatter(_fetch(), "# Doc")
        assert "render_engine" not in fm
        assert "js_executed" not in fm
