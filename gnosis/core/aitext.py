"""ai.txt / llms.txt consent discovery, recorded into provenance.

`ai.txt` (spawning.ai) is a site's machine-readable declaration of how AI
agents may crawl and use its content. `llms.txt` (llmstxt.org) is a curated
index of a site's LLM-relevant pages. gnosis records both, when present, in
the frontmatter of every captured document from that host.

Fetching is advisory: a missing or disallowed file does not block capture.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Per-host cache so a crawl does not re-fetch the consent files for every page.
_cache: dict[str, dict] = {}


def parse_ai_txt(text: str) -> dict[str, str]:
    """Parse ai.txt directives into a lowercase key -> value dict."""
    directives: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            directives[key.strip().lower()] = value.strip()
    return directives


def summarize_ai_txt(directives: dict[str, str]) -> dict[str, str]:
    """Reduce ai.txt directives to the provenance-relevant subset."""
    return {k: directives[k] for k in ("training", "data", "allow", "disallow") if k in directives}


async def fetch_host_consent(url: str, downloader) -> dict:
    """Fetch ai.txt + llms.txt for a host; return `{ai_txt?, llms_txt?}` (cached)."""
    parsed = urlparse(url)
    host = parsed.netloc
    if not host or parsed.scheme not in ("http", "https"):
        return {}
    if host in _cache:
        return _cache[host]

    result: dict = {}
    base = f"{parsed.scheme}://{host}"

    try:
        fetch = await downloader.fetch_result(f"{base}/ai.txt")
        if fetch.status_code == 200:
            summary = summarize_ai_txt(parse_ai_txt(fetch.html))
            if summary:
                result["ai_txt"] = summary
    except Exception:
        pass

    try:
        fetch = await downloader.fetch_result(f"{base}/llms.txt")
        if fetch.status_code == 200:
            result["llms_txt"] = True
    except Exception:
        pass

    _cache[host] = result
    return result
