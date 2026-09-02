"""
Website crawler for discovering and downloading child pages.

Crawls websites starting from a base URL, discovering links and downloading
pages that match the same domain and path prefix. Supports parallel fetches
via configurable concurrent_requests.
"""

import asyncio
import posixpath
from collections import deque
from typing import AsyncIterator, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from gnosis.config.settings import CrawlerSettings
from gnosis.core.downloader import Downloader, DownloadError, FetchResult
from gnosis.core.network import PrivateNetworkBlocked


class Crawler:
    """
    Async website crawler for downloading all pages under a URL.

    Discovers links on each page and downloads pages that match the
    same domain and path prefix as the starting URL. Fetches up to
    concurrent_requests pages in parallel batches.
    """

    def __init__(
        self,
        settings: Optional[CrawlerSettings] = None,
        downloader: Optional[Downloader] = None,
    ):
        """
        Initialize the crawler.

        Args:
            settings: Crawler configuration settings.
            downloader: HTTP downloader instance.
        """
        self.settings = settings or CrawlerSettings()
        self.downloader = downloader or Downloader()

    async def discover_pages(self, start_url: str) -> Tuple[int, list[str], bool]:
        """
        Discover all pages under a URL without processing them.

        Performs the discovery pass using sequential fetches (discovery is
        metadata-only — provenance is captured during the real crawl pass).

        Args:
            start_url: The starting URL to discover from.

        Returns:
            Tuple of (total_count, discovered_urls, hit_max_limit)
        """
        start_url = self._normalize_url(start_url)
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc
        base_path = self._get_base_path(parsed_start.path)

        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque()
        queue.append((start_url, 0))

        discovered_urls: list[str] = []
        hit_max_limit = False

        while queue and len(discovered_urls) < self.settings.max_pages:
            url, depth = queue.popleft()

            if url in visited:
                continue
            visited.add(url)

            try:
                html = await self.downloader.fetch(url)
            except (DownloadError, PrivateNetworkBlocked):
                continue

            discovered_urls.append(url)

            if depth >= self.settings.max_depth:
                continue

            links = self._extract_links(html, url, base_domain, base_path)
            for link in links:
                if link not in visited:
                    queue.append((link, depth + 1))

        if len(discovered_urls) >= self.settings.max_pages and queue:
            hit_max_limit = True

        return len(discovered_urls), discovered_urls, hit_max_limit

    async def crawl(self, start_url: str) -> AsyncIterator[Tuple[str, FetchResult]]:
        """
        Crawl a website starting from the given URL.

        Yields (url, fetch_result) tuples for each page discovered. Only pages
        matching the same domain and path prefix are crawled.

        When concurrent_requests > 1, pages are fetched in parallel batches.
        BFS ordering is approximate with concurrency but bounded by the
        configured max_depth.

        Args:
            start_url: The starting URL to crawl from.

        Yields:
            Tuples of (url, FetchResult) carrying HTML and provenance
            metadata (final URL, status code, fetch timestamp, headers).
        """
        start_url = self._normalize_url(start_url)
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc
        base_path = self._get_base_path(parsed_start.path)

        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque()
        queue.append((start_url, 0))

        concurrency = max(1, self.settings.concurrent_requests)
        pages_yielded = 0

        while queue and pages_yielded < self.settings.max_pages:
            # Collect a batch of up to concurrency URLs to fetch in parallel
            batch: list[Tuple[str, int]] = []
            while (
                queue
                and len(batch) < concurrency
                and pages_yielded + len(batch) < self.settings.max_pages
            ):
                url, depth = queue.popleft()
                if url in visited:
                    continue
                visited.add(url)
                batch.append((url, depth))

            if not batch:
                break

            # Fetch the batch in parallel; exceptions are caught per-page
            tasks = [self.downloader.fetch_result(url) for url, _ in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (url, depth), result in zip(batch, results):
                if isinstance(result, Exception):
                    continue

                pages_yielded += 1
                yield url, result

                # Extract links for the next depth level
                if depth < self.settings.max_depth:
                    links = self._extract_links(
                        result.html, url, base_domain, base_path
                    )
                    for link in links:
                        if link not in visited:
                            queue.append((link, depth + 1))

    def _get_base_path(self, path: str) -> str:
        """
        Extract the base path prefix for crawl scope.

        If the last segment looks like a file (contains a dot), returns its
        parent directory. Otherwise returns the path as-is.
        """
        path = path.rstrip("/")
        last_segment = posixpath.basename(path)
        if "." in last_segment:
            return posixpath.dirname(path)
        return path

    def _normalize_url(self, url: str) -> str:
        """Normalize a URL: strip fragment and trailing slash (except root)."""
        parsed = urlparse(url)
        scheme = parsed.scheme or "https"
        path = parsed.path
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return urlunparse((scheme, parsed.netloc, path, parsed.params, parsed.query, ""))

    def _extract_links(
        self, html: str, page_url: str, base_domain: str, base_path: str
    ) -> list[str]:
        """
        Extract links from HTML that match the base domain and path prefix.

        Relative links below extensionless "directory" URLs are resolved
        with directory semantics (trailing slash appended), mirroring
        _get_base_path, so links don't escape the crawl scope.
        """
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]

            if not href or href == "#" or href.startswith(("javascript:", "mailto:", "tel:")):
                continue

            base = page_url
            if not base.endswith("/"):
                last_segment = posixpath.basename(urlparse(base).path)
                if "." not in last_segment:
                    base += "/"
            absolute_url = urljoin(base, href)

            normalized = self._normalize_url(absolute_url)
            parsed = urlparse(normalized)

            if parsed.netloc != base_domain:
                continue
            if not (parsed.path == base_path or parsed.path.startswith(base_path + "/")):
                continue

            path_lower = parsed.path.lower()
            if any(
                path_lower.endswith(ext)
                for ext in (
                    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
                    ".ico", ".css", ".js", ".json", ".xml", ".zip",
                    ".tar", ".gz", ".mp3", ".mp4", ".webm",
                    ".woff", ".woff2", ".ttf", ".eot",
                )
            ):
                continue

            links.append(normalized)

        return links
