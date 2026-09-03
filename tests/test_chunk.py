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


def test_pre_heading_content_preserved():
    md = "Intro before any heading.\n\n" + MD
    chunks = chunk_markdown(md)
    assert chunks[0].heading_path == []
    assert "Intro before any heading" in chunks[0].content


def test_offsets_are_document_relative():
    md = "Intro.\n\n" + MD
    chunks = chunk_markdown(md)
    for c in chunks:
        assert c.char_count == c.end - c.start
        assert md[c.start:c.end] == c.content
    # second chunk (first heading) must start after the intro, not at 0
    assert chunks[1].start > 0


def test_oversized_split_offsets_document_relative():
    big = "# Big\n\n" + "\n\n".join("p" * 100 for _ in range(10))
    chunks = chunk_markdown(big, max_chars=300)
    split = [c for c in chunks if "." in c.chunk_id]
    assert split
    assert any(c.start > 0 for c in split)  # document-relative, not all part-relative 0
    assert all(c.char_count == c.end - c.start for c in split)


def test_token_aware_and_exact_spans():
    big = "# Big\n\n" + "\n\n".join("word " * 30 for _ in range(60))
    chunks = chunk_markdown(big)
    assert any("." in c.chunk_id for c in chunks), "oversized section should split"
    for c in chunks:
        assert c.token_count > 0
        assert big[c.start:c.end] == c.content


def test_manifest_has_token_and_sha():
    import hashlib
    chunks = chunk_markdown(MD)
    manifest = chunk_manifest("d", "h", chunks)
    assert all("token_count" in e and "chunk_sha256" in e for e in manifest)
    assert manifest[0]["chunk_sha256"] == hashlib.sha256(chunks[0].content.encode()).hexdigest()


def test_cjk_splits_under_token_budget():
    cjk = "# 中文\n\n" + "你好世界。" * 300
    chunks = chunk_markdown(cjk, max_tokens=512)
    assert any("." in c.chunk_id for c in chunks)


def test_hard_token_budget_enforced_latin():
    """A single unbroken block larger than max_tokens must be hard-split so
    every chunk stays within budget (was: soft, could blow the budget)."""
    block = " ".join(["alpha"] * 400)  # 400 latin tokens, no sentence breaks
    md = "# H\n\n" + block
    chunks = chunk_markdown(md, max_tokens=128, overlap_tokens=0)
    assert chunks
    for c in chunks:
        assert c.token_count <= 128, c.token_count
        assert md[c.start:c.end] == c.content  # offsets stay exact


def test_hard_token_budget_enforced_cjk():
    """CJK text has no spaces: a single run must still be sliced token-aware."""
    block = "\u6c49" * 400  # 400 CJK chars = 400 tokens, unbroken
    md = "# H\n\n" + block
    chunks = chunk_markdown(md, max_tokens=100, overlap_tokens=0)
    assert chunks
    for c in chunks:
        assert c.token_count <= 100, c.token_count
        assert md[c.start:c.end] == c.content


def test_cjk_overlap_stays_in_budget():
    """Regression (#50): overlap tail must be token-aware; CJK chunks must not
    exceed max_tokens when overlap is enabled."""
    md = "# H\n\n" + "\u3002".join(["\u6c49\u5b57" * 100] * 8) + "\u3002"
    chunks = chunk_markdown(md, max_tokens=64, overlap_tokens=16)
    assert chunks
    for c in chunks:
        assert c.token_count <= 64, c.token_count
        assert md[c.start:c.end] == c.content


def test_oversized_flush_resets_token_count():
    """Regression (#51): a stale cur_tokens after an oversized-piece flush must
    not inflate the next window's token_count."""
    from gnosis.core.chunk import estimate_tokens

    md = (
        "# H\n\n"
        + "word " * 10 + ". "
        + "\u6c49" * 600 + "\u3002 "
        + "word " * 10 + ". "
        + "word " * 10 + "."
    )
    chunks = chunk_markdown(md, max_tokens=128, overlap_tokens=0)
    for c in chunks:
        assert c.token_count == estimate_tokens(c.content), c.token_count


def test_overlap_flush_stays_in_budget():
    """Regression (reviewer P1): after carrying the overlap tail, the next
    window must still respect max_tokens even for a large incoming piece."""
    md = "\u6c49" * 50 + "\u3002 " + "\u6c49" * 50
    chunks = chunk_markdown(md, max_tokens=64, overlap_tokens=16)
    assert chunks
    for c in chunks:
        assert c.token_count <= 64, c.token_count
        assert md[c.start:c.end] == c.content


def test_fence_aware_headings():
    """Regression (#62): '#' lines inside fenced code blocks must not be treated
    as headings."""
    md = "# Real\n\n```python\n# not a heading\n```\n\n## After\n\ncontent"
    chunks = chunk_markdown(md, max_tokens=128, overlap_tokens=0)
    paths = [c.heading_path for c in chunks]
    assert all("not a heading" not in p for p in paths)
    assert any(p == ["Real"] for p in paths)
    assert any(p == ["Real", "After"] for p in paths)
