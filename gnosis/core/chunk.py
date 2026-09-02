"""Split markdown into retrievable, citable chunks.

Each chunk carries a stable id, its heading path, char offsets, and size,
so a downstream RAG pipeline can anchor citations back to a chunk.
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
    sections = _sections(markdown)
    chunks: list[Chunk] = []
    for idx, (path, content, start, end) in enumerate(sections):
        if len(content) <= max_chars:
            chunks.append(Chunk(f"c{idx}", path, content, start, end, len(content)))
        else:
            for j, part in enumerate(_paragraphs(content, max_chars)):
                chunks.append(Chunk(f"c{idx}.{j}", path, part, 0, len(part), len(part)))
    return chunks


def _sections(markdown: str) -> list[tuple[list[str], str, int, int]]:
    lines = markdown.split("\n")
    headings = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))

    if not headings:
        return [([], markdown.strip(), 0, len(markdown))]

    sections = []
    stack: list[tuple[int, str]] = []
    for si, (line_idx, level, title) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = [t for _, t in stack]
        start_line = line_idx
        end_line = headings[si + 1][0] if si + 1 < len(headings) else len(lines)
        content = "\n".join(lines[start_line:end_line]).strip()
        start = _offset(lines, start_line)
        end = _offset(lines, end_line)
        sections.append((path, content, start, end))
    return sections


def _paragraphs(content: str, max_chars: int) -> list[str]:
    parts = [p for p in re.split(r"\n\n+", content) if p.strip()]
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for p in parts:
        if cur and cur_len + len(p) + 2 > max_chars:
            out.append("\n\n".join(cur))
            cur = []
            cur_len = 0
        cur.append(p)
        cur_len += len(p) + 2
    if cur:
        out.append("\n\n".join(cur))
    return out


def _offset(lines: list[str], upto_line: int) -> int:
    return sum(len(line) + 1 for line in lines[:upto_line])


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
