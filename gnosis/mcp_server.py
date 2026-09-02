"""MCP (Model Context Protocol) server exposing gnosis as tools.

`gnosis-mcp` serves a `fetch_and_convert` tool that returns provenance-stamped
Markdown (url, content_hash, bytes_sha256, status_code, fetched_at). The `mcp`
SDK is imported lazily so it stays an optional extra
(`pip install 'gnosis-markdown[mcp]'`).
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
    except ImportError as exc:  # pragma: no cover - exercised via [mcp] extra
        raise SystemExit(
            "gnosis-mcp requires the 'mcp' package. "
            "Install it with: pip install 'gnosis-markdown[mcp]'"
        ) from exc

    mcp = FastMCP("gnosis")
    mcp.tool(
        name="fetch_and_convert",
        description="Fetch a URL and convert it to Markdown with byte-level provenance.",
    )(
        fetch_and_convert
    )
    mcp.run()
