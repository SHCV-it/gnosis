"""robots.txt handling for polite, standards-respecting crawling.

Uses Python's `urllib.robotparser` (RFC 9309) for allow/disallow matching,
and parses `Crawl-delay` directly (the stdlib's `crawl_delay()` is unreliable
across versions). Fetching is async (httpx) with per-origin caching.

Fail-open semantics: if robots.txt cannot be fetched (network error, 404, 5xx),
the URL is treated as allowed — consistent with common crawler practice.
"""

import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from gnosis.core.network import build_transport

DEFAULT_TIMEOUT = 10.0

_CRAWL_DELAY_RE = re.compile(r"(?im)^\s*crawl-delay\s*:\s*(\d+(?:\.\d+)?)")


class RobotsChecker:
    """Fetch, cache, and query robots.txt per origin."""

    def __init__(
        self,
        user_agent: str,
        respect: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        allow_private_network: bool = False,
    ) -> None:
        self.user_agent = user_agent
        self.respect = respect
        self.timeout = timeout
        self.allow_private_network = allow_private_network
        self._parsers: dict[str, RobotFileParser] = {}
        self._crawl_delays: dict[str, float | None] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # SSRF guard enforced via a pinned transport (same boundary as the
            # downloader) — robots.txt must not be an SSRF channel either.
            transport = build_transport(self.allow_private_network)
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"User-Agent": self.user_agent, "Accept": "text/plain"},
                transport=transport,
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
        crawl_delay: float | None = None
        try:
            client = await self._get_client()
            response = await client.get(f"{origin}/robots.txt")
            if response.status_code == 200:
                text = response.text
                parser.parse(text.splitlines())
                match = _CRAWL_DELAY_RE.search(text)
                if match:
                    try:
                        crawl_delay = float(match.group(1))
                    except ValueError:
                        crawl_delay = None
            else:
                # Non-200 => no restrictions => allow all (fail-open).
                parser.allow_all = True
        except httpx.HTTPError:
            # Network failure => allow all (fail-open).
            parser.allow_all = True

        self._parsers[origin] = parser
        self._crawl_delays[origin] = crawl_delay
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
        origin = self._origin(url)
        if origin not in self._crawl_delays:
            await self._parser(url)
        return self._crawl_delays.get(origin)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
