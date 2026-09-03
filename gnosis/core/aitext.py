"""ai.txt / llms.txt consent discovery, recorded into provenance.

`ai.txt` (spawning.ai) is a site's machine-readable declaration of how AI
agents may crawl and use its content. `llms.txt` (llmstxt.org) is a curated
index of a site's LLM-relevant pages. gnosis records both, when present, in
the frontmatter of every captured document from that host.

Fetching is advisory: a missing or disallowed file does not block capture.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

# Per-host cache so a crawl does not re-fetch the consent files for every page.
# Entries expire after _CACHE_TTL_SECONDS so long-lived processes (MCP/library)
# do not hold stale consent state forever.
_cache: dict[tuple[str, str], tuple[dict, float]] = {}
_CACHE_TTL_SECONDS = 300.0


def clear_consent_cache() -> None:
    """Clear the consent cache. Call between unrelated jobs (library/MCP use)."""
    _cache.clear()


def parse_ai_txt(text: str, user_agent: str = "Gnosis") -> dict[str, str]:
    """Parse ai.txt directives, resolving User-Agent groups.

    ai.txt is robots.txt-style: directives are scoped to a `User-Agent` group.
    The result is the directive set for the most specific group matching
    `user_agent`, falling back to the `*` group. Full-line and trailing `#`
    comments are ignored; empty-valued directives are skipped.
    """
    groups: dict[str, dict[str, str]] = {"*": {}}
    current = "*"
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("user-agent:"):
            current = line.partition(":")[2].strip().lower()
            groups.setdefault(current, {})
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            value = value.partition("#")[0].strip()
            if value:
                groups[current][key.strip().lower()] = value

    ua = user_agent.lower()
    # robots.txt product-token prefix matching: the longest group token that is a
    # prefix of the crawler's UA wins; fall back to "*".
    best = None
    for group in groups:
        if group != "*" and ua.startswith(group) and (best is None or len(group) > len(best)):
            best = group
    if best is not None:
        return dict(groups[best])
    return dict(groups.get("*", {}))


_DENY_VALUES = {"deny", "disallow", "no", "opt-out", "optout", "forbidden", "prohibited", "false", "never"}
_ALLOW_VALUES = {"allow", "yes", "opt-in", "optin", "permitted", "true", "always"}


def _normalize_directive(value: str) -> str:
    """Canonicalise common ai.txt directive values to Allow/Deny."""
    v = value.strip().lower()
    if v in _DENY_VALUES:
        return "Deny"
    if v in _ALLOW_VALUES:
        return "Allow"
    return value.strip()


def summarize_ai_txt(directives: dict[str, str]) -> dict[str, str]:
    """Reduce ai.txt directives to the provenance-relevant subset.

    `training`/`data` values are normalised so that Deny/Disallow/no/opt-out
    all map to "Deny" (and Allow/yes/opt-in to "Allow"); `allow`/`disallow`
    path lists are kept verbatim.
    """
    out: dict[str, str] = {}
    for key in ("training", "data"):
        if key in directives:
            out[key] = _normalize_directive(directives[key])
    for key in ("allow", "disallow"):
        if key in directives:
            out[key] = directives[key]
    return out


async def fetch_host_consent(url: str, downloader) -> dict:
    """Fetch ai.txt + llms.txt for a host; return `{ai_txt?, llms_txt?}` (cached).

    Results are cached per (scheme, host) for `_CACHE_TTL_SECONDS`. A failed
    probe (absent, 404, or transient error) records nothing for that file, and
    the (possibly empty) result is cached for the TTL duration.
    """
    parsed = urlparse(url)
    host = parsed.netloc
    if not host or parsed.scheme not in ("http", "https"):
        return {}
    key = (parsed.scheme, host)
    now = time.monotonic()
    if key in _cache:
        result, cached_at = _cache[key]
        if now - cached_at < _CACHE_TTL_SECONDS:
            return result

    result: dict = {}
    base = f"{parsed.scheme}://{host}"

    try:
        fetch = await downloader.fetch_result(f"{base}/ai.txt")
        if fetch.status_code == 200:
            ua = getattr(downloader.settings, "user_agent", "Gnosis")
            summary = summarize_ai_txt(parse_ai_txt(fetch.html, user_agent=ua))
            if summary:
                result["ai_txt"] = summary
    except Exception:
        # ai.txt absent/unreachable is NOT an error for consent discovery —
        # proceed to llms.txt so its presence is still recorded.
        pass

    try:
        fetch = await downloader.fetch_result(f"{base}/llms.txt")
        if fetch.status_code == 200:
            result["llms_txt"] = True
    except Exception:
        pass

    _cache[key] = (result, time.monotonic())
    return result
