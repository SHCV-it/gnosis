"""Split markdown into retrievable, citable chunks.

Each chunk carries a stable id, its heading path, document-relative char
offsets, and size, so a downstream RAG pipeline can anchor citations back
to the exact source span (`markdown[start:end] == chunk.content`).
"""

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 2000

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    chunk_id: str
    heading_path: list[str]
    content: str
    start: int
    end: int
    char_count: int


def chunk_markdown(markdown: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    """Split markdown into heading-scoped chunks, paragraph-splitting oversized ones."""
    lines = markdown.split("\n")
    offsets = _line_offsets(lines)
    headings = [
        (i, len(m.group(1)), m.group(2).strip())
        for i, line in enumerate(lines)
        if (m := _HEADING_RE.match(line))
    ]

    sections: list[tuple[list[str], int, int]] = []  # (heading_path, start_line, end_line)
    if headings:
        first = headings[0][0]
        if any(ln.strip() for ln in lines[:first]):
            sections.append(([], 0, first))
        stack: list[tuple[int, str]] = []
        for si, (line_idx, level, title) in enumerate(headings):
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = [t for _, t in stack]
            end_line = headings[si + 1][0] if si + 1 < len(headings) else len(lines)
            sections.append((path, line_idx, end_line))
    elif markdown.strip():
        sections.append(([], 0, len(lines)))

    chunks: list[Chunk] = []
    for idx, (path, sl, el) in enumerate(sections):
        start = offsets[sl]
        end = offsets[el]
        text = "\n".join(lines[sl:el])
        if end - start <= max_chars:
            chunks.append(Chunk(f"c{idx}", path, text, start, end, end - start))
        else:
            for j, (psl, pel) in enumerate(_paragraph_ranges(lines, sl, el, max_chars)):
                pstart = offsets[psl]
                pend = offsets[pel]
                ptext = "\n".join(lines[psl:pel])
                chunks.append(Chunk(f"c{idx}.{j}", path, ptext, pstart, pend, pend - pstart))
    return chunks


def _paragraph_ranges(
    lines: list[str], sl: int, el: int, max_chars: int
) -> list[tuple[int, int]]:
    """Group non-blank line runs into (start, end) ranges ≤ max_chars."""
    runs: list[tuple[int, int]] = []
    run_start = None
    for i in range(sl, el):
        if lines[i].strip():
            if run_start is None:
                run_start = i
        elif run_start is not None:
            runs.append((run_start, i))
            run_start = None
    if run_start is not None:
        runs.append((run_start, el))

    ranges: list[tuple[int, int]] = []
    cur_start = None
    cur_end = None
    cur_chars = 0
    for rs, re_ in runs:
        rchars = sum(len(lines[i]) + 1 for i in range(rs, re_))
        if cur_start is not None and cur_chars + rchars > max_chars:
            ranges.append((cur_start, cur_end))
            cur_start, cur_end, cur_chars = None, None, 0
        if cur_start is None:
            cur_start, cur_end, cur_chars = rs, re_, rchars
        else:
            cur_end = re_
            cur_chars += rchars
    if cur_start is not None:
        ranges.append((cur_start, cur_end))
    return ranges


def _line_offsets(lines: list[str]) -> list[int]:
    offsets = [0]
    total = 0
    for line in lines:
        total += len(line) + 1
        offsets.append(total)
    return offsets


def chunk_manifest(doc_id: str, content_hash: str, chunks: list[Chunk]) -> list[dict]:
    """Build a per-chunk manifest with stable citation anchors."""
    return [
        {
            "doc_id": doc_id,
            "content_hash": content_hash,
            "chunk_id": c.chunk_id,
            "heading_path": c.heading_path,
            "start": c.start,
            "end": c.end,
            "char_count": c.char_count,
        }
        for c in chunks
    ]
