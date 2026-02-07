"""
HTTP downloader for fetching web pages.

Uses httpx for async HTTP requests with retry and rate limiting support.
"""

import asyncio
from typing import Optional

import httpx

from gnosis.config.settings import DownloaderSettings


class DownloadError(Exception):
    """Raised when a download fails after all retries."""

    pass


class Downloader:
    """
    Async HTTP downloader with retry and rate limiting.

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

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.timeout),
                follow_redirects=True,
                headers={
                    "User-Agent": self.settings.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
            )
        return self._client

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        if self.settings.rate_limit_ms <= 0:
            return

        now = asyncio.get_event_loop().time()
        elapsed_ms = (now - self._last_request_time) * 1000

        if elapsed_ms < self.settings.rate_limit_ms:
            wait_time = (self.settings.rate_limit_ms - elapsed_ms) / 1000
            await asyncio.sleep(wait_time)

        self._last_request_time = asyncio.get_event_loop().time()

    async def fetch(self, url: str) -> str:
        """
        Fetch the HTML content of a URL.

        Args:
            url: The URL to fetch.

        Returns:
            The HTML content as a string.

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

                return response.text

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
