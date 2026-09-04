"""Tests for LlamaIndex / LangChain reader document mapping (no deps)."""

from gnosis.integrations.langchain import _to_document as lc_doc
from gnosis.integrations.llamaindex import _to_document as li_doc

RESULT = {
    "url": "https://example.com/page",
    "markdown": "# Hello\n",
    "content_hash": "a" * 64,
    "bytes_sha256": "b" * 64,
    "status_code": 200,
    "fetched_at": "2026-09-03T00:00:00Z",
}


def test_llamaindex_document_mapping():
    d = li_doc(RESULT)
    assert d["text"] == "# Hello\n"
    assert d["metadata"]["url"] == "https://example.com/page"
    assert d["metadata"]["content_hash"] == "a" * 64
    assert d["metadata"]["bytes_sha256"] == "b" * 64


def test_langchain_document_mapping():
    d = lc_doc(RESULT)
    assert d["page_content"] == "# Hello\n"
    assert d["metadata"]["source"] == "https://example.com/page"
    assert d["metadata"]["content_hash"] == "a" * 64
    assert d["metadata"]["bytes_sha256"] == "b" * 64
