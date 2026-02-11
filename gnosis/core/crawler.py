"""
Website crawler for discovering and downloading child pages.

Crawls websites starting from a base URL, discovering links and downloading
pages that match the same domain and path prefix.
"""

import asyncio
import posixpath
from collections import deque
from typing import AsyncIterator, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from gnosis.config.settings import CrawlerSettings
from gnosis.core.downloader import Downloader, DownloadError


class Crawler:
    """
    Async website crawler for downloading all pages under a URL.

    Discovers links on each page and downloads pages that match the
    same domain and path prefix as the starting URL.
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

        Performs the same crawling logic as crawl() but only counts pages
        and collects URLs without yielding HTML content.

        Args:
            start_url: The starting URL to discover from.

        Returns:
            Tuple of (total_count, discovered_urls, hit_max_limit)
        """
        # Normalize the starting URL
        start_url = self._normalize_url(start_url)
        parsed_start = urlparse(start_url)

        # Extract the base path prefix
        base_domain = parsed_start.netloc
        base_path = self._get_base_path(parsed_start.path)

        # Track visited URLs and queue
        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque()  # (url, depth)
        queue.append((start_url, 0))

        discovered_urls: list[str] = []
        hit_max_limit = False

        while queue and len(discovered_urls) < self.settings.max_pages:
            # Get next URL
            url, depth = queue.popleft()

            # Skip if already visited
            if url in visited:
                continue

            visited.add(url)

            # Download the page to extract links
            try:
                html = await self.downloader.fetch(url)
            except DownloadError:
                continue

            # Add to discovered list
            discovered_urls.append(url)

            # Don't discover links if at max depth
            if depth >= self.settings.max_depth:
                continue

            # Extract links from the page
            links = self._extract_links(html, url, base_domain, base_path)

            # Add new links to queue
            for link in links:
                if link not in visited:
                    queue.append((link, depth + 1))

        # Check if we hit the max_pages limit with more pages in queue
        if len(discovered_urls) >= self.settings.max_pages and queue:
            hit_max_limit = True

        return len(discovered_urls), discovered_urls, hit_max_limit

    async def crawl(self, start_url: str) -> AsyncIterator[Tuple[str, str]]:
        """
        Crawl a website starting from the given URL.

        Yields (url, html) tuples for each page discovered. Only pages
        matching the same domain and path prefix are crawled.

        Args:
            start_url: The starting URL to crawl from.

        Yields:
            Tuples of (url, html_content) for each page.
        """
        # Normalize the starting URL
        start_url = self._normalize_url(start_url)
        parsed_start = urlparse(start_url)

        # Extract the base path prefix
        base_domain = parsed_start.netloc
        base_path = self._get_base_path(parsed_start.path)

        # Track visited URLs and queue
        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque()  # (url, depth)
        queue.append((start_url, 0))

        pages_yielded = 0

        while queue and pages_yielded < self.settings.max_pages:
            # Get next URL
            url, depth = queue.popleft()

            # Skip if already visited
            if url in visited:
                continue

            visited.add(url)

            # Download the page
            try:
                html = await self.downloader.fetch(url)
            except DownloadError:
                continue

            # Yield the page
            pages_yielded += 1
            yield url, html

            # Don't discover links if at max depth
            if depth >= self.settings.max_depth:
                continue

            # Extract links from the page
            links = self._extract_links(html, url, base_domain, base_path)

            # Add new links to queue
            for link in links:
                if link not in visited:
                    queue.append((link, depth + 1))

    def _get_base_path(self, path: str) -> str:
        """
        Extract the base path prefix for crawl scope.

        If the path looks like a file (last segment contains a dot),
        returns the parent directory. Otherwise returns the path as-is.

        Args:
            path: URL path component.

        Returns:
            Base path prefix for matching discovered URLs.
        """
        path = path.rstrip("/")
        # Check if last segment looks like a file (e.g. page.html)
        last_segment = posixpath.basename(path)
        if "." in last_segment:
            return posixpath.dirname(path)
        return path

    def _normalize_url(self, url: str) -> str:
        """
        Normalize a URL for consistent comparison.

        Args:
            url: The URL to normalize.

        Returns:
            Normalized URL string.
        """
        parsed = urlparse(url)

        # Ensure scheme
        scheme = parsed.scheme or "https"

        # Remove fragment
        # Remove trailing slash from path (except for root)
        path = parsed.path
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        # Rebuild URL without fragment
        normalized = urlunparse(
            (scheme, parsed.netloc, path, parsed.params, parsed.query, "")
        )

        return normalized

    def _extract_links(
        self, html: str, page_url: str, base_domain: str, base_path: str
    ) -> list[str]:
        """
        Extract links from HTML that match the base domain and path.

        Args:
            html: HTML content to parse.
            page_url: URL of the current page (for resolving relative links).
            base_domain: Domain to match.
            base_path: Path prefix to match.

        Returns:
            List of matching URLs.
        """
        soup = BeautifulSoup(html, "lxml")
        links = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]

            # Skip empty, bare anchor (#), or javascript/mailto/tel links
            # Bare "#" is typically a dropdown toggle or placeholder, not a real link.
            # Fragment links like "#installation" are valid same-page anchors that
            # resolve to the current page URL via urljoin.
            if not href or href == "#" or href.startswith(("javascript:", "mailto:", "tel:")):
                continue

            # Resolve relative URLs
            absolute_url = urljoin(page_url, href)

            # Normalize
            normalized = self._normalize_url(absolute_url)

            # Check if it matches our criteria
            parsed = urlparse(normalized)

            # Must be same domain
            if parsed.netloc != base_domain:
                continue

            # Must be under base path (or equal to it)
            if not parsed.path.startswith(base_path):
                continue

            # Skip non-HTML resources
            path_lower = parsed.path.lower()
            if any(
                path_lower.endswith(ext)
                for ext in (
                    ".pdf",
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".svg",
                    ".ico",
                    ".css",
                    ".js",
                    ".json",
                    ".xml",
                    ".zip",
                    ".tar",
                    ".gz",
                    ".mp3",
                    ".mp4",
                    ".webm",
                    ".woff",
                    ".woff2",
                    ".ttf",
                    ".eot",
                )
            ):
                continue

            links.append(normalized)

        return links
