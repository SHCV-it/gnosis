"""Tests for the optional document converter."""

import pytest

from gnosis.integrations.documents import convert_document


def test_missing_markitdown_raises_helpful(tmp_path):
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ImportError, match=r"pip install gnosis-markdown\[docs\]"):
        convert_document(doc)
