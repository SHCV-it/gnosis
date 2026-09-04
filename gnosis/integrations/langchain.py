"""LangChain document loader (optional extra: `gnosis-markdown[langchain]`).

Loads a URL into LangChain `Document`s carrying provenance metadata (source,
content_hash, bytes_sha256) so a LangChain pipeline can cite or verify the
source of every document.
"""

from __future__ import annotations

from gnosis.mcp_server import fetch_and_convert


def _to_document(result: dict) -> dict:
    """Map a fetch_and_convert result to a document dict (no dependency)."""
    return {
        "page_content": result["markdown"],
        "metadata": {
            "source": result["url"],
            "content_hash": result["content_hash"],
            "bytes_sha256": result["bytes_sha256"],
        },
    }


class GnosisLoader:
    """Load a URL as LangChain Documents with byte-level provenance."""

    async def aload(self, url: str) -> list:
        try:
            from langchain_core.documents import Document
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "GnosisLoader requires langchain-core. "
                "Install with: pip install 'gnosis-markdown[langchain]'"
            ) from exc
        d = _to_document(await fetch_and_convert(url))
        return [Document(page_content=d["page_content"], metadata=d["metadata"])]

    def load(self, url: str) -> list:
        import asyncio

        return asyncio.run(self.aload(url))
