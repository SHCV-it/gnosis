"""Tests for the optional document converter."""

import importlib.util

import pytest

from gnosis.integrations.documents import convert_document

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("markitdown") is not None,
    reason="markitdown is installed; this test requires it to be absent",
)


def test_missing_markitdown_raises_helpful(tmp_path):
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ImportError, match=r"pip install gnosis-markdown\[docs\]"):
        convert_document(doc)
