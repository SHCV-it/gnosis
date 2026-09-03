"""Split markdown into retrievable, citable, token-aware chunks.

Each chunk carries a stable id, its heading path, document-relative char
offsets (the citation anchor — `markdown[start:end] == chunk.content` always
holds), a token estimate, and, when overlap is enabled, the overlapping tail
carried forward from the previous window.

Tokenization is a projection, not the source of truth: sizes are driven by a
dependency-free heuristic (`word-runs/4` + 1-per-CJK-char, matching the
GPT-family within ~15%), and `token_count` is recorded in the manifest.
"""

import hashlib
import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 2000  # legacy char-mode default
DEFAULT_MAX_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64
CHARS_PER_TOKEN = 4

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BREAK_RE = re.compile(r"(?<=[.!?。！？])\s+|\n\s*\n")
_CJK = "\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af\uf900-\ufaff"
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(f"[{_CJK}]")


@dataclass
class Chunk:
    chunk_id: str
    heading_path: list[str]
    content: str
    start: int
    end: int
    char_count: int
    token_count: int = 0


def estimate_tokens(text: str) -> int:
    """Dependency-free token estimate (word-runs/4 + 1 per CJK char)."""
    words = sum((len(m.group(0)) + 3) // 4 for m in _WORD_RE.finditer(text))
    cjk = len(_CJK_RE.findall(text))
    return max(1, words + cjk)


def _line_offsets(lines: list[str]) -> list[int]:
    offs = [0]
    total = 0
    for line in lines:
        total += len(line) + 1
        offs.append(total)
    return offs


def _offset(offs: list[int], lines: list[str], sl: int, el: int) -> tuple[int, int]:
    """Return the exact document char span [start, end) for lines[sl:el]."""
    if sl >= el:
        return offs[sl], offs[sl]
    return offs[sl], offs[el - 1] + len(lines[el - 1])


def _pieces(text: str, base: int) -> list[tuple[str, int, int]]:
    """Split text on sentence/paragraph boundaries -> (text, doc_start, doc_end)."""
    pieces: list[tuple[str, int, int]] = []
    pos = 0
    for m in _BREAK_RE.finditer(text):
        end = m.end()
        seg = text[pos:end]
        if seg.strip():
            pieces.append((seg, base + pos, base + end))
        pos = end
    tail = text[pos:]
    if tail.strip():
        pieces.append((tail, base + pos, base + len(text)))
    return pieces


def _token_tail(text: str, overlap_tokens: int) -> str:
    """Longest suffix of text with a token estimate <= overlap_tokens.

    Token-aware (not char-based): CJK is 1 token/char, so a char-based tail
    would exceed the overlap budget.
    """
    if overlap_tokens <= 0:
        return ""
    start = max(0, len(text) - overlap_tokens * CHARS_PER_TOKEN)
    tail = text[start:]
    while tail and estimate_tokens(tail) > overlap_tokens:
        tail = tail[1:]
    return tail


def _split_oversized(
    text: str, base: int, max_tokens: int, overlap_tokens: int
) -> list[tuple[str, int, int, int]]:
    """Pack pieces into token-budgeted windows with overlap (citation spans may overlap)."""
    pieces = _pieces(text, base)
    windows: list[tuple[str, int, int, int]] = []
    cur: list[str] = []
    cur_start = cur_end = base
    cur_tokens = 0

    for ptext, pstart, pend in pieces:
        ptokens = estimate_tokens(ptext)
        if ptokens > max_tokens:
            # a single unbreakable piece exceeds the budget -> hard split it
            if cur:
                windows.append(("".join(cur), cur_start, cur_end, cur_tokens))
                cur = []
                cur_tokens = 0
            windows.extend(_hard_split(ptext, pstart, max_tokens))
            cur_start = cur_end = pend
            continue
        if cur and cur_tokens + ptokens > max_tokens:
            content = "".join(cur)
            windows.append((content, cur_start, cur_end, cur_tokens))
            tail = _token_tail(content, overlap_tokens)
            cur = [tail] if tail else []
            cur_start = cur_end - len(tail)
            cur_end = cur_start + len(tail)
            cur_tokens = estimate_tokens(tail)
        if not cur:
            cur_start = pstart
            cur_end = pstart
        cur.append(ptext)
        cur_end = pend
        cur_tokens += ptokens

    if cur:
        windows.append(("".join(cur), cur_start, cur_end, cur_tokens))
    return windows


def _slice_run(run: str, start: int, max_tokens: int) -> list[tuple[str, int, int, int]]:
    """Token-aware char slicing of a single unbroken run (CJK + latin safe)."""
    out: list[tuple[str, int, int, int]] = []
    pos = 0
    n = len(run)
    while pos < n:
        end = pos + 1
        while end <= n and estimate_tokens(run[pos:end]) <= max_tokens:
            end += 1
        seg = run[pos:end - 1]
        if not seg:
            seg = run[pos:pos + 1]
            end = pos + 1
        out.append((seg, start + pos, start + pos + len(seg), estimate_tokens(seg)))
        pos += len(seg)
    return out


def _hard_split(text: str, base: int, max_tokens: int) -> list[tuple[str, int, int, int]]:
    """Hard-split a single unbreakable piece into token-budgeted spans.

    Packs whitespace-delimited runs greedily so every span's token estimate
    stays <= max_tokens; a single run that alone exceeds the budget (an
    unbroken blob, e.g. CJK text or a giant code line) is sliced token-aware.
    """
    out: list[tuple[str, int, int, int]] = []
    buf: list[str] = []
    buf_tokens = 0
    buf_start = base
    for m in re.finditer(r"\S+\s*", text):
        run = m.group(0)
        rtok = estimate_tokens(run)
        if rtok > max_tokens:
            if buf:
                content = "".join(buf)
                out.append((content, buf_start, base + m.start(), buf_tokens))
                buf, buf_tokens = [], 0
            out.extend(_slice_run(run, base + m.start(), max_tokens))
            buf_start = base + m.end()
            continue
        if buf and buf_tokens + rtok > max_tokens:
            content = "".join(buf)
            out.append((content, buf_start, base + m.start(), buf_tokens))
            buf, buf_tokens = [], 0
            buf_start = base + m.start()
        buf.append(run)
        buf_tokens += rtok
    if buf:
        content = "".join(buf)
        out.append((content, buf_start, base + len(text), buf_tokens))
    return out


def chunk_markdown(
    markdown: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split markdown into heading-scoped, token-budgeted chunks."""
    lines = markdown.split("\n")
    offs = _line_offsets(lines)
    headings = [
        (i, len(m.group(1)), m.group(2).strip())
        for i, line in enumerate(lines)
        if (m := _HEADING_RE.match(line))
    ]

    sections: list[tuple[list[str], int, int]] = []
    if headings:
        first = headings[0][0]
        if any(ln.strip() for ln in lines[:first]):
            sections.append(([], 0, first))
        stack: list[tuple[int, str]] = []
        for si, (li, lvl, title) in enumerate(headings):
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, title))
            path = [t for _, t in stack]
            el = headings[si + 1][0] if si + 1 < len(headings) else len(lines)
            sections.append((path, li, el))
    elif markdown.strip():
        sections.append(([], 0, len(lines)))

    # legacy char mode -> token budget derived from chars, no overlap
    if max_chars != DEFAULT_MAX_CHARS:
        max_tokens = max(1, max_chars // CHARS_PER_TOKEN)
        overlap_tokens = 0

    chunks: list[Chunk] = []
    for idx, (path, sl, el) in enumerate(sections):
        text = "\n".join(lines[sl:el])
        if not text.strip():
            continue
        start, end = _offset(offs, lines, sl, el)
        toks = estimate_tokens(text)
        if toks > max_tokens:
            for j, (wtext, ws, we, wtok) in enumerate(
                _split_oversized(text, start, max_tokens, overlap_tokens)
            ):
                chunks.append(Chunk(f"c{idx}.{j}", path, wtext, ws, we, we - ws, wtok))
        else:
            chunks.append(Chunk(f"c{idx}", path, text, start, end, end - start, toks))

    return chunks


def chunk_manifest(doc_id: str, content_hash: str, chunks: list[Chunk]) -> list[dict]:
    """Build a per-chunk manifest with citation anchors and token metadata."""
    return [
        {
            "doc_id": doc_id,
            "content_hash": content_hash,
            "chunk_id": c.chunk_id,
            "heading_path": c.heading_path,
            "start": c.start,
            "end": c.end,
            "char_count": c.char_count,
            "token_count": c.token_count,
            "chunk_sha256": hashlib.sha256(c.content.encode("utf-8")).hexdigest(),
        }
        for c in chunks
    ]
