"""Tests for crawler link extraction and URL handling."""

import asyncio

from gnosis.config.settings import CrawlerSettings
from gnosis.core.crawler import Crawler
from gnosis.core.downloader import FetchResult


def extract(html: str, page_url: str, base_domain: str, base_path: str) -> list[str]:
    crawler = Crawler(CrawlerSettings())
    return crawler._extract_links(html, page_url, base_domain, base_path)


class TestRelativeLinkResolution:
    def test_directory_url_keeps_relative_links_in_scope(self):
        """Regression: '/en/latest' + 'quickstart.html' must resolve under
        '/en/latest/', not '/en/'."""
        html = '<a href="quickstart.html">q</a>'
        links = extract(
            html,
            "https://docs.example.com/en/latest",
            "docs.example.com",
            "/en/latest",
        )
        assert "https://docs.example.com/en/latest/quickstart.html" in links

    def test_file_url_resolves_relative_to_parent(self):
        html = '<a href="other.html">o</a>'
        links = extract(
            html,
            "https://docs.example.com/guide/intro.html",
            "docs.example.com",
            "/guide",
        )
        assert "https://docs.example.com/guide/other.html" in links

    def test_trailing_slash_url_resolves_beneath(self):
        html = '<a href="sub/page.html">s</a>'
        links = extract(
            html,
            "https://docs.example.com/guide/",
            "docs.example.com",
            "/guide",
        )
        assert "https://docs.example.com/guide/sub/page.html" in links

    def test_query_string_does_not_break_directory_resolution(self):
        """Regression (#42): a query string must not cause relative links to
        resolve to the parent directory."""
        links = extract(
            '<a href="quickstart.html">q</a>',
            "https://docs.example.com/en/latest?lang=en",
            "docs.example.com",
            "/en/latest",
        )
        assert "https://docs.example.com/en/latest/quickstart.html" in links


class TestScopeFiltering:
    def test_external_domain_excluded(self):
        html = '<a href="https://other.com/en/latest/x.html">x</a>'
        assert extract(html, "https://docs.example.com/en/latest", "docs.example.com", "/en/latest") == []

    def test_out_of_scope_path_excluded(self):
        html = '<a href="/other/page.html">x</a>'
        assert extract(html, "https://docs.example.com/en/latest", "docs.example.com", "/en/latest") == []

    def test_assets_excluded(self):
        html = '<a href="/en/latest/logo.png">img</a><a href="/en/latest/real.html">ok</a>'
        links = extract(html, "https://docs.example.com/en/latest", "docs.example.com", "/en/latest")
        assert links == ["https://docs.example.com/en/latest/real.html"]

    def test_bare_anchor_and_javascript_skipped(self):
        html = '<a href="#">top</a><a href="javascript:void(0)">js</a><a href="/en/latest/a.html">a</a>'
        links = extract(html, "https://docs.example.com/en/latest", "docs.example.com", "/en/latest")
        assert links == ["https://docs.example.com/en/latest/a.html"]

    def test_fragments_stripped_for_dedup(self):
        html = '<a href="/en/latest/a.html#section">a</a>'
        links = extract(html, "https://docs.example.com/en/latest", "docs.example.com", "/en/latest")
        assert links == ["https://docs.example.com/en/latest/a.html"]


class TestUrlNormalization:
    def test_trailing_slash_removed(self):
        crawler = Crawler(CrawlerSettings())
        assert (
            crawler._normalize_url("https://example.com/docs/")
            == "https://example.com/docs"
        )

    def test_fragment_removed(self):
        crawler = Crawler(CrawlerSettings())
        assert (
            crawler._normalize_url("https://example.com/docs#frag")
            == "https://example.com/docs"
        )



class _FakeDownloader:
    def __init__(self):
        self.fetched = []

    async def fetch_result(self, url):
        self.fetched.append(url)
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            html="<a href='/a'>a</a>",
            fetched_at="2026-01-01T00:00:00Z",
            raw_bytes=b"<html></html>",
        )


def test_crawl_no_skip_fetches():
    async def _run():
        dl = _FakeDownloader()
        crawler = Crawler(CrawlerSettings(max_depth=0), dl)
        urls = [u async for u, _ in crawler.crawl("http://x.test/")]
        return urls, dl.fetched

    urls, fetched = asyncio.run(_run())
    assert fetched == ["http://x.test/"]


def test_get_base_path_dotted_directory():
    """Regression (#43): a versioned directory root (/v2.0/) is a directory,
    not a file, so its base path is /v2.0 (not /)."""
    crawler = Crawler(CrawlerSettings())
    assert crawler._get_base_path("/v2.0/") == "/v2.0"
    assert crawler._get_base_path("/guide/intro.html") == "/guide"
    assert crawler._get_base_path("/en/latest") == "/en/latest"
