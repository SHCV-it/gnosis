"""Tests for markdown chunking."""

from gnosis.core.chunk import chunk_manifest, chunk_markdown

MD = """# Title

Intro paragraph.

## Section A

Paragraph A1.

Paragraph A2.

## Section B

Paragraph B1.
"""


def test_splits_by_heading():
    chunks = chunk_markdown(MD)
    ids = [c.chunk_id for c in chunks]
    assert "c0" in ids and "c1" in ids and "c2" in ids
    assert chunks[0].heading_path == ["Title"]
    assert "# Title" in chunks[0].content
    assert chunks[1].heading_path == ["Title", "Section A"]


def test_no_headings_single_chunk():
    chunks = chunk_markdown("Just a paragraph.")
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "c0"
    assert chunks[0].heading_path == []


def test_oversized_chunk_split_by_paragraph():
    big = "# Big\n\n" + "\n\n".join("p" * 100 for _ in range(10))
    chunks = chunk_markdown(big, max_chars=300)
    assert any("." in c.chunk_id for c in chunks)


def test_manifest_fields():
    chunks = chunk_markdown(MD)
    manifest = chunk_manifest("doc1", "hash123", chunks)
    assert len(manifest) == len(chunks)
    entry = manifest[0]
    assert entry["doc_id"] == "doc1"
    assert entry["content_hash"] == "hash123"
    assert "chunk_id" in entry
    assert "heading_path" in entry
    assert "char_count" in entry
