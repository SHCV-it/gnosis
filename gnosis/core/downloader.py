"""
HTTP downloader for fetching web pages.

Uses httpx for async HTTP requests with retry and rate limiting support.
Supports bearer/basic/custom-header authentication (secrets via environment
variables) and returns rich fetch results carrying provenance metadata.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional
from urllib.parse import urlparse

import httpx

from gnosis.config.settings import DownloaderSettings
from gnosis.core.network import build_transport, check_ip_literal
from gnosis.core.robots import RobotsChecker


class DownloadError(Exception):
    """Raised when a download fails after all retries."""

    pass


class RobotsDisallowed(DownloadError):
    """Raised when robots.txt disallows fetching a URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"Blocked by robots.txt: {url}")


@dataclass
class FetchResult:
    """
    Result of fetching one URL, including provenance metadata.

    Attributes:
        url: The URL as requested.
        final_url: The URL after following redirects.
        status_code: HTTP status code of the final response.
        html: Response body decoded as text.
        fetched_at: UTC timestamp (ISO 8601) of the fetch.
        response_headers: Final response headers (lowercase keys).
        raw_bytes: Raw response body bytes (for byte-level hashing / WARC).
        content_type: Response Content-Type header value.
        redirect_chain: URLs followed through redirects (final URL last).
    """

    url: str
    final_url: str
    status_code: int
    html: str
    fetched_at: str
    response_headers: dict[str, str] = field(default_factory=dict)
    raw_bytes: bytes = b""
    content_type: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    render_engine: str = ""
    render_version: str = ""
    render_timestamp: str = ""
    js_executed: bool = False


class Downloader:
    """
    Async HTTP downloader with retry, rate limiting, and auth support.

    Attributes:
        settings: Downloader configuration settings.
    """

    def __init__(self, settings: Optional[DownloaderSettings] = None):
        """
        Initialize the downloader.

        Args:
            settings: Downloader settings. Uses defaults if None.
        """
        self.settings = settings or DownloaderSettings()
        self._last_request_times: dict[str | None, float] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._host_locks: dict[str | None, asyncio.Lock] = {}
        self._robots = RobotsChecker(
            self.settings.user_agent,
            respect=self.settings.respect_robots,
            allow_private_network=self.settings.allow_private_network,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            # Custom headers and auth override/extend the defaults
            headers.update(self.settings.request_headers())
            # The SSRF guard is enforced at the transport/connect layer (IP
            # pinning) so every request and every redirect hop is covered with
            # a single resolve-then-dial step; no separate validate-then-connect
            # hook that a rebinding resolver could race.
            transport = build_transport(self.settings.allow_private_network)
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.timeout),
                follow_redirects=True,
                headers=headers,
                transport=transport,
            )
        return self._client

    async def _rate_limit(self, url: str | None = None) -> None:
        """Apply rate limiting between requests (per-host; safe for concurrent use)."""
        delay_ms = self.settings.rate_limit_ms
        key: str | None = None
        if url is not None:
            key = urlparse(url).hostname or urlparse(url).netloc
            crawl_delay = await self._robots.crawl_delay(url)
            if crawl_delay:
                delay_ms = max(delay_ms, int(crawl_delay * 1000))
        if delay_ms <= 0:
            return

        # Per-host lock: a slow host's Crawl-delay must not stall other hosts.
        lock = self._host_locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = asyncio.get_running_loop().time()
            last = self._last_request_times.get(key, 0.0)
            elapsed_ms = (now - last) * 1000

            if elapsed_ms < delay_ms:
                await asyncio.sleep((delay_ms - elapsed_ms) / 1000)

            self._last_request_times[key] = asyncio.get_running_loop().time()

    async def fetch_result(self, url: str, extra_headers: Optional[dict] = None) -> FetchResult:
        """
        Fetch a URL and return the full result with provenance metadata.

        Args:
            url: The URL to fetch.

        Returns:
            FetchResult with HTML, final URL, status code, timestamp, headers.

        Raises:
            DownloadError: If the download fails after all retries.
        """
        if not self.settings.allow_private_network:
            # DNS-free fast-fail for IP literals; hostnames are resolved and
            # pinned exactly once at connect time (see PinnedNetworkBackend).
            check_ip_literal(urlparse(url).hostname or "")

        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(self.settings.retries + 1):
            try:
                if not await self._robots.is_allowed(url):
                    raise RobotsDisallowed(url)
                await self._rate_limit(url)

                response = await client.get(url, headers=extra_headers or None)
                response.raise_for_status()

                return FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    html=response.text,
                    fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    response_headers={k.lower(): v for k, v in response.headers.items()},
                    raw_bytes=response.content,
                    content_type=response.headers.get("content-type", ""),
                    redirect_chain=[str(r.url) for r in response.history] + [str(response.url)],
                )

            except httpx.HTTPStatusError as e:
                last_error = e
                # Don't retry on client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    break
            except httpx.RequestError as e:
                last_error = e

            # Wait before retry (exponential backoff)
            if attempt < self.settings.retries:
                wait_time = 2**attempt
                await asyncio.sleep(wait_time)

        raise DownloadError(f"Failed to download {url}: {last_error}")

    async def fetch(self, url: str) -> str:
        """
        Fetch the HTML content of a URL.

        Convenience wrapper around fetch_result() for callers that only
        need the body (e.g. the crawler's link-discovery pass).

        Args:
            url: The URL to fetch.

        Returns:
            The HTML content as a string.

        Raises:
            DownloadError: If the download fails after all retries.
        """
        return (await self.fetch_result(url)).html

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        await self._robots.close()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
