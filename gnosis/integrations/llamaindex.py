"""LlamaIndex reader integration (optional extra: `gnosis-markdown[llamaindex]`).

Fetches a URL and returns LlamaIndex `Document`s carrying provenance metadata
(url, content_hash, bytes_sha256, status_code, fetched_at) so a RAG pipeline
can cite or verify the source of every chunk.
"""

from __future__ import annotations

from gnosis.mcp_server import fetch_and_convert


def _to_document(result: dict) -> dict:
    """Map a fetch_and_convert result to a document dict (no dependency)."""
    return {
        "text": result["markdown"],
        "metadata": {
            "url": result["url"],
            "content_hash": result["content_hash"],
            "bytes_sha256": result["bytes_sha256"],
            "status_code": result["status_code"],
            "fetched_at": result["fetched_at"],
        },
    }


class GnosisReader:
    """Load a URL as LlamaIndex Documents with byte-level provenance."""

    async def aload_data(self, url: str) -> list:
        try:
            from llama_index.core.schema import Document
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "GnosisReader requires llama-index-core. "
                "Install with: pip install 'gnosis-markdown[llamaindex]'"
            ) from exc
        d = _to_document(await fetch_and_convert(url))
        return [Document(text=d["text"], metadata=d["metadata"])]

    def load_data(self, url: str) -> list:
        import asyncio

        return asyncio.run(self.aload_data(url))
