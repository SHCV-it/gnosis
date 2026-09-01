"""robots.txt handling for polite, standards-respecting crawling.

Uses Python's `urllib.robotparser` (RFC 9309) for parsing and matching,
and httpx for async fetching with per-origin caching. Fail-open semantics:
if robots.txt cannot be fetched (network error, 404, 5xx), the URL is
treated as allowed — consistent with common crawler practice.
"""

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

DEFAULT_TIMEOUT = 10.0


class RobotsChecker:
    """Fetch, cache, and query robots.txt per origin."""

    def __init__(
        self,
        user_agent: str,
        respect: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.user_agent = user_agent
        self.respect = respect
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"User-Agent": self.user_agent, "Accept": "text/plain"},
            )
        return self._client

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def _parser(self, url: str) -> RobotFileParser:
        origin = self._origin(url)
        parser = self._parsers.get(origin)
        if parser is not None:
            return parser

        parser = RobotFileParser()
        try:
            client = await self._get_client()
            response = await client.get(f"{origin}/robots.txt")
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            # Any other status => empty ruleset => allow all (RFC 9309).
        except httpx.HTTPError:
            # Network failure => allow all (fail-open).
            pass
        self._parsers[origin] = parser
        return parser

    async def is_allowed(self, url: str) -> bool:
        """Return True if the URL may be fetched under this robots.txt."""
        if not self.respect:
            return True
        parser = await self._parser(url)
        return parser.can_fetch(self.user_agent, url)

    async def crawl_delay(self, url: str) -> float | None:
        """Return the Crawl-delay (seconds) for this URL's origin, if any."""
        if not self.respect:
            return None
        parser = await self._parser(url)
        return parser.crawl_delay(self.user_agent)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
