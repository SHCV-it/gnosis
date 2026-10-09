"""MCP (Model Context Protocol) server exposing gnosis as tools.

`gnosis-mcp` serves a `fetch_and_convert` tool that returns provenance-stamped
Markdown (url, content_hash, bytes_sha256, status_code, fetched_at). The `mcp`
SDK is imported lazily: it is a core dependency on Python 3.10+, but gnosis
still installs and runs on 3.9 where the MCP server is unavailable.
"""

from __future__ import annotations

from gnosis.config.settings import Settings
from gnosis.core.converter import HTMLToMarkdownConverter
from gnosis.core.downloader import Downloader
from gnosis.core.provenance import build_frontmatter


async def fetch_and_convert(url: str, settings: Settings | None = None) -> dict:
    """Fetch a URL and convert it to Markdown with byte-level provenance.

    Returns a dict with `markdown` plus the provenance fields (url,
    content_hash, bytes_sha256, status_code, fetched_at) so an MCP client can
    cite or verify the captured document.
    """
    settings = settings or Settings()
    async with Downloader(settings.downloader) as downloader:
        fetch = await downloader.fetch_result(url)
    converter = HTMLToMarkdownConverter(settings.converter)
    metadata = converter.extract_metadata(fetch.html)
    markdown = converter.convert(fetch.html, base_url=fetch.final_url)
    metadata["retention_ratio"] = converter.stats.retention_ratio
    metadata["stripped_elements"] = converter.stats.stripped_elements
    if converter.stats.markdown_chars < 150:
        metadata["low_content"] = True
    frontmatter = build_frontmatter(fetch, markdown, metadata)
    return {
        "url": fetch.final_url,
        "markdown": markdown,
        "content_hash": frontmatter["content_hash"],
        "bytes_sha256": frontmatter["bytes_sha256"],
        "status_code": fetch.status_code,
        "fetched_at": fetch.fetched_at,
    }


def main() -> None:
    """Run the MCP server over stdio (requires the `mcp` package)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - reached on py<3.10 (mcp absent)
        raise SystemExit(
            "gnosis-mcp requires the 'mcp' package (Python 3.10+). "
            "Install with: pip install gnosis-markdown"
        ) from exc

    mcp = FastMCP("gnosis")

    async def _tool(url: str) -> dict:
        # The tool surface is `url` ONLY — never expose `settings`, or a client
        # could pass allow_private_network=true and disable the SSRF guard.
        return await fetch_and_convert(url)

    mcp.tool(
        name="fetch_and_convert",
        description="Fetch a URL and convert it to Markdown with byte-level provenance.",
    )(_tool)
    mcp.run()
