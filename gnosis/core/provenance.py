"""
Provenance frontmatter for converted documents.

Every markdown file gnosis writes carries a YAML frontmatter block recording
where the content came from, when it was fetched, and how to verify it:
source URL, fetch timestamp, content hash, HTTP status, and page metadata.
This makes each file self-describing and safe to feed into knowledge
pipelines (dedup, audit, re-fetch) without any external bookkeeping.
"""

import hashlib
from typing import Optional

import yaml

from gnosis import __version__
from gnosis.core.downloader import FetchResult

# Response headers worth preserving as provenance hints.
_HEADER_PROVENANCE_KEYS = ("etag", "last-modified")


def compute_content_hash(markdown: str) -> str:
    """
    Compute the SHA-256 hash of a markdown body.

    Args:
        markdown: The markdown content (body only, without frontmatter).

    Returns:
        Lowercase hex digest.
    """
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def build_frontmatter(
    fetch: FetchResult,
    markdown: str,
    metadata: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> dict:
    """
    Build the provenance frontmatter dict for a converted document.

    Args:
        fetch: The fetch result carrying URL, status, timestamp, headers.
        markdown: The converted markdown body (hashed for content_hash).
        metadata: Page metadata from HTMLToMarkdownConverter.extract_metadata().
        extra: User-supplied constant fields (merged last; cannot override
               the core provenance keys).

    Returns:
        Ordered dict suitable for YAML serialization.
    """
    metadata = metadata or {}

    frontmatter: dict = {
        "title": metadata.get("title") or "",
        "url": fetch.final_url or fetch.url,
        "fetched_at": fetch.fetched_at,
        "content_hash": compute_content_hash(markdown),
        "status_code": fetch.status_code,
        "generator": f"gnosis/{__version__}",
    }

    if metadata.get("language"):
        frontmatter["language"] = metadata["language"]
    if metadata.get("author"):
        frontmatter["author"] = metadata["author"]
    if metadata.get("description"):
        frontmatter["description"] = metadata["description"]
    if metadata.get("site_name"):
        frontmatter["site_name"] = metadata["site_name"]
    if metadata.get("published_time"):
        frontmatter["published_time"] = metadata["published_time"]
    if metadata.get("modified_time"):
        frontmatter["modified_time"] = metadata["modified_time"]

    for key in _HEADER_PROVENANCE_KEYS:
        value = fetch.response_headers.get(key)
        if value:
            frontmatter[key.replace("-", "_")] = value

    if fetch.url != fetch.final_url:
        frontmatter["requested_url"] = fetch.url

    # User extras: merged first-class but never clobber core provenance
    for key, value in (extra or {}).items():
        if key not in frontmatter:
            frontmatter[key] = value

    return frontmatter


def render_document(frontmatter: dict, body: str) -> str:
    """
    Render a markdown document with a YAML frontmatter header.

    The frontmatter is standard YAML between '---' fences, parseable by
    python-frontmatter, Jekyll, Hugo, Obsidian, and friends.

    Args:
        frontmatter: Dict from build_frontmatter().
        body: Markdown body.

    Returns:
        Complete document string.
    """
    yaml_block = yaml.safe_dump(
        frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).strip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"
