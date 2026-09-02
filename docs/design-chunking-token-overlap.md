# Design — Token-aware chunking + overlap (`chunk_markdown()`)

Panel item: **chunk-lib**. Author: chunking panel member. Status: proposal.

## 1. Current state (verified in `gnosis/core/chunk.py`)

- `chunk_markdown(markdown, max_chars=2000)` — char-based, heading-scoped,
  splits oversized sections by blank-line paragraph runs.
- `Chunk(chunk_id, heading_path, content, start, end, char_count)`.
- No overlap. No token count. Manifest emits only `char_count`.
- Offsets computed with `markdown.find(text, search_pos)`.

### Real defects this design must fix (not just "add tokens")

1. **A single paragraph larger than `max_chars` is never split.**
   `_paragraph_ranges` only *groups* non-blank runs; it never splits a run.
   A 5k-char paragraph silently becomes one oversized chunk.
2. **Offsets are fragile.** `markdown.find(...)` assumes each chunk text is
   unique and contiguous; it's O(n²)-ish and breaks on repeated content.
   Offsets should come from known line/char positions, not substring search.
3. **`char_count` is Python code points**, not bytes and not tokens — so there
   is no notion of an embedding/LLM budget at all.
4. **Accounting drift.** `_paragraph_ranges` sums `len(line)+1`, which
   double-counts the trailing newline vs. the actual `"\n".join(...)` length.

## 2. Decisions (opinionated)

| Question | Decision |
| --- | --- |
| Token vs char | **Token as the sizing unit** (`max_tokens`, `overlap_tokens`). **Char stays the anchoring unit** (offsets). |
| Default tokenizer | Deterministic, zero-dep **`CharTokenizer(4)`** (≈2000 chars → 500 tokens, matches old default). **`tiktoken` (`cl100k_base`) as an optional `[chunk]` extra** for exact BPE; a `WordTokenizer` heuristic ships too. |
| Boundaries | Ordered markdown precedence: paragraph `\n\n` → block-start `\n` (list/quote/code/table) → line `\n` → sentence `.!?;:` → word `\s+` → hard char split. |
| Overlap | **Token-budgeted, boundary-anchored.** Default 50 tokens. Realized by re-including whole boundary units, never mid-unit. |
| Heading context | Metadata (`heading_path`) + the natural overlap tail. **Content stays byte-exact — no injected breadcrumb.** |
| Provenance invariant | **`markdown[start:end] == chunk.content` always**, tested. `start`/`end` are code-point offsets; `token_count` is computed, not derived from slicing. |

## 3. The exact API

### 3.1 Tokenizer protocol + built-ins

```python
from typing import Protocol

class Tokenizer(Protocol):
    name: str
    def count(self, text: str) -> int: ...

@dataclass(frozen=True)
class CharTokenizer:
    chars_per_token: int = 4
    name: str = "char"
    def count(self, text: str) -> int:
        return max(1, math.ceil(len(text) / self.chars_per_token))

@dataclass(frozen=True)
class WordTokenizer:          # English-prose heuristic; code blocks fall back to char/4
    name: str = "word"
    def count(self, text: str) -> int: ...

class TikTokenTokenizer:      # optional extra: gnosis-markdown[chunk]
    name: str = "tiktoken"
    def __init__(self, encoding: str = "cl100k_base"): ...
    def count(self, text: str) -> int:
        return len(self._enc.encode(text))
```

### 3.2 `Chunk` (extended)

```python
@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    heading_path: list[str]
    content: str            # == markdown[start:end]  (invariant)
    start: int              # code-point offset, inclusive
    end: int                # code-point offset, exclusive
    char_count: int         # len(content) — kept for back-compat
    token_count: int        # tokenizer.count(content)
    overlap_with_prev: bool = False
```

### 3.3 `chunk_markdown()` — breaking, keyword-only after `markdown`

```python
DEFAULT_BOUNDARIES = (
    ("paragraph", r"\n{2,}"),
    ("block",     r"\n(?=[#>*\-+]|\d+\.\s|```|~~~|\|)"),
    ("line",      r"\n"),
    ("sentence",  r"(?<=[.!?;:])\s+(?=[A-Z0-9])"),
    ("word",      r"\s+"),
)

def chunk_markdown(
    markdown: str,
    *,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
    min_chunk_tokens: int = 100,
    tokenizer: Tokenizer | None = None,           # default CharTokenizer(4)
    strategy: Literal["structure", "fixed", "recursive"] = "structure",
    boundaries: tuple[tuple[str, str], ...] = DEFAULT_BOUNDARIES,
) -> list[Chunk]:
```

**Semantics:**

- `max_tokens` — soft ceiling. A chunk may exceed it only when a single
  atomic unit is larger than `max_tokens`; then the unit is hard-split at a
  char boundary after all boundary levels fail.
- `overlap_tokens` — when a chunk closes, the next chunk re-includes the
  smallest suffix of *whole boundary units* whose token count ≥
  `overlap_tokens`, capped at `max_tokens // 2`. First chunk:
  `overlap_with_prev=False`.
- `min_chunk_tokens` — a trailing chunk below this is merged into the previous
  one (overlap dropped), unless it is the only chunk.
- `strategy`:
  - `"structure"` (default) — heading-scoped segmentation first (preserves the
    current citation story), then recursive boundary splitting of oversized
    sections, then token-aware packing. **Recommended for RAG/citations.**
  - `"recursive"` — ignore headings as hard boundaries; apply boundary
    precedence to the whole document. For heading-less corpora.
  - `"fixed"` — fixed sliding window; `overlap_tokens` is the stride. For
    pure feed-into-LLM use.
- `boundaries` — ordered `(name, regex)` pairs; a `None`/empty entry disables
  that level. Overridable without forking.

## 4. Algorithm (the part that matters)

1. **Segment** into heading sections as today → `(heading_path, start, end)`,
   but compute `start`/`end` from line positions (no `find`).
2. **Atomize** each section into blank-line-separated blocks (paragraphs, list
   blocks, code fences kept intact).
3. **Recursive boundary split** (oversized atoms only): try `boundaries` in
   order, split at the last match ≤ `max_tokens` from the front, recurse; only
   hard-split a single atom at a char index when every level yields a unit
   still > `max_tokens`.
4. **Pack with overlap**: greedily accumulate atoms while `tokens ≤ max_tokens`;
   on overflow close the chunk and roll back the `overlap_tokens`-worth tail of
   whole units into the next chunk's start.
5. **Anchor**: derive `start`/`end` from atom ranges; assert
   `markdown[start:end] == content`; set `token_count = tokenizer.count(content)`.

## 5. Manifest

```python
def chunk_manifest(doc_id, content_hash, chunks) -> list[dict]:
    # adds token_count, overlap_with_prev; keeps start/end/char_count
```

```json
{
  "doc_id": "https://docs.example.com",
  "content_hash": "1549512c...",
  "chunk_id": "c0",
  "heading_path": ["Title"],
  "start": 0,
  "end": 812,
  "char_count": 812,
  "token_count": 203,
  "overlap_with_prev": false
}
```

## 6. Config + CLI wiring

`ChunkingSettings` in `gnosis/config/settings.py` + a `chunking:` block in
`default.yaml`:

```yaml
chunking:
  max_tokens: 500
  overlap_tokens: 50
  min_chunk_tokens: 100
  strategy: structure          # structure | recursive | fixed
  tokenizer: char              # char | word | tiktoken
  tiktoken_encoding: cl100k_base
```

CLI: add `--chunk-max-tokens`, `--chunk-overlap` (config is the primary path).
`_write_chunk_manifest(...)` gains a `settings` argument and passes the
`chunking` block through to `chunk_markdown`.

## 7. Migration / back-compat

- `max_chars` is removed (breaking). Only two call sites:
  `cli/main.py::_write_chunk_manifest` and `tests/test_chunk.py` — both updated
  in the same change.
- `CharTokenizer(4)` + `max_tokens=500` reproduces the old ~2000-char default.
- `chunk_id` scheme (`c0`, `c0.1`) unchanged → existing citations stay valid
  for non-overlapping cases.

## 8. Why these choices

1. **Token is the right sizing unit because the consumer is an LLM/embedding
   model, not a text editor.** But token counts must not own the anchors: the
   gnosis moat ("bytes are the source of truth") means offsets stay code-point
   indices and `markdown[start:end] == content` is an invariant.
2. **Zero-dep default, tiktoken optional** — matches the architecture spine
   ("heavy deps as extras, never statically linked"). `CharTokenizer(4)` is
   within ±30% for budget-setting; opt into tiktoken for exact budgets.
3. **Overlap must be boundary-anchored.** Naive char-overlap sews garbage at
   chunk seams — the #1 RAG quality killer after wrong chunk size. Rolling back
   to the previous whole unit keeps overlap *and* clean edges. Overlap is also
   what carries heading context into continuation chunks without polluting
   `content`.
4. **"structure" as default** because heading-scoped chunks are already
   gnosis's citation story (heading_path + stable ids). "recursive"/"fixed"
   exist for heading-less corpora and pure LLM feeding.
5. **The single-oversized-paragraph bug is in scope** — token-aware chunking is
   meaningless if a 4k-token paragraph escapes as one chunk.

## 9. Acceptance criteria (testable)

1. Deterministic: same input + config → same chunks/ids/offsets across runs.
2. Every chunk: `markdown[start:end] == content`,
   `token_count == tokenizer.count(content)`, `char_count == len(content)`.
3. A single paragraph 10× `max_tokens` is split into chunks each ≤ `max_tokens`
   (+ one-unit slop), with correct document-relative offsets.
4. Overlap windows are whole boundary units (no mid-word/mid-sentence seam);
   window token count ≥ `overlap_tokens` when the source is large enough.
5. First chunk `overlap_with_prev == False`; later ones `True` only when
   overlap was actually applied.
6. `heading_path` + `chunk_id` unchanged for the simple heading case (back-compat).
7. Manifest includes `token_count` and `overlap_with_prev`; JSON round-trips.
8. `chunking:` config block + `--chunk-*` flags flow into `_write_chunk_manifest`.
9. Updated `test_chunk.py` + new tests for (2)–(7) are green.
