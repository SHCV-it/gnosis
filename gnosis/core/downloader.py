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


class DownloadError(Exception):
    """Raised when a download fails after all retries."""

    pass


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
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.timeout),
                follow_redirects=True,
                headers=headers,
            )
        return self._client

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests (safe for concurrent use)."""
        if self.settings.rate_limit_ms <= 0:
            return

        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            elapsed_ms = (now - self._last_request_time) * 1000

            if elapsed_ms < self.settings.rate_limit_ms:
                wait_time = (self.settings.rate_limit_ms - elapsed_ms) / 1000
                await asyncio.sleep(wait_time)

            self._last_request_time = asyncio.get_event_loop().time()

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
        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(self.settings.retries + 1):
            try:
                await self._rate_limit()

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

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
