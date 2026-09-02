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

import httpx

from gnosis.config.settings import DownloaderSettings
from gnosis.core.network import assert_public_url
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
        self._last_request_time: float = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_lock: asyncio.Lock = asyncio.Lock()
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
            event_hooks = {} if self.settings.allow_private_network else {"request": [self._ssrf_guard]}
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.timeout),
                follow_redirects=True,
                headers=headers,
                event_hooks=event_hooks,
            )
        return self._client

    async def _rate_limit(self, url: str | None = None) -> None:
        """Apply rate limiting between requests (safe for concurrent use)."""
        delay_ms = self.settings.rate_limit_ms
        if url is not None:
            crawl_delay = await self._robots.crawl_delay(url)
            if crawl_delay:
                delay_ms = max(delay_ms, int(crawl_delay * 1000))
        if delay_ms <= 0:
            return

        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            elapsed_ms = (now - self._last_request_time) * 1000

            if elapsed_ms < delay_ms:
                await asyncio.sleep((delay_ms - elapsed_ms) / 1000)

            self._last_request_time = asyncio.get_event_loop().time()

    async def _ssrf_guard(self, request: httpx.Request) -> None:
        """Block requests targeting private/reserved networks (SSRF guard)."""
        await assert_public_url(str(request.url))

    async def fetch_result(self, url: str) -> FetchResult:
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
            await assert_public_url(url)

        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(self.settings.retries + 1):
            try:
                if not await self._robots.is_allowed(url):
                    raise RobotsDisallowed(url)
                await self._rate_limit(url)

                response = await client.get(url)
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
