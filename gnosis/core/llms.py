"""llms.txt / llms-full.txt emission + sitemap discovery.

Follows the llmstxt.org convention: an `llms.txt` is a Markdown map of a
site's important pages for AI agents, and `llms-full.txt` is the full
concatenated content.
"""

from defusedxml import ElementTree as ET

from gnosis.core.downloader import Downloader

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def render_llms_txt(site_name: str, pages: list[dict]) -> str:
    """Render an llms.txt index for the crawled pages."""
    lines = [
        f"# {site_name}",
        "",
        "> Crawled by gnosis — clean, provenance-stamped, LLM-friendly markdown.",
        "",
        "## Pages",
        "",
    ]
    for p in pages:
        lines.append(f"- [{p['title']}]({p['url']})")
    return "\n".join(lines).rstrip() + "\n"


def render_llms_full(pages: list[dict]) -> str:
    """Render llms-full.txt (full concatenated content of every page)."""
    blocks = []
    for p in pages:
        blocks.append(f"# {p['title']}\n\nSource: {p['url']}\n\n{p['markdown']}")
    return "\n\n---\n\n".join(blocks).rstrip() + "\n"


async def fetch_sitemap_urls(url: str, downloader: Downloader) -> list[str]:
    """Fetch a sitemap.xml and return the page URLs it lists."""
    fetch = await downloader.fetch_result(url)
    try:
        root = ET.fromstring(fetch.raw_bytes)
    except (ET.ParseError, ValueError):
        # Reject DOCTYPE/entity-expansion and any malformed XML outright —
        # sitemap discovery is best-effort and must never be a DoS vector.
        return []
    return [loc.text for loc in root.findall(".//sm:loc", _SITEMAP_NS) if loc.text]
