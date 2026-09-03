# Design — Token-aware chunking + overlap: **compatibility review**

Panel item: **chunk-compat**. Author: chunking panel member (compat reviewer).
Status: proposal — reviews and constrains the `chunk-lib` proposal in
`docs/design-chunking-token-overlap.md`.

## Verdict

The `chunk-lib` proposal is technically sound but **breaks the public contract
in four places** (removes `max_chars`, freezes `Chunk`, makes `token_count`
required, and changes the module-level default behavior). All four are
avoidable without losing the feature. Fix them and the item ships as an
**additive, minor-version change**; ship as-is and it is a **breaking major**
for a library whose stated moat is *stability of the citation contract*.

---

## 1. What is actually public (the real contract to protect)

`chunk.py`'s functions are **not** in `gnosis/core/__init__.py.__all__`, so they
are semi-public. The truly public surface is broader than the functions:

| Surface | Location | Must not change |
| --- | --- | --- |
| Manifest **file name** | `<page>.md.chunks.json` | `cli/main.py:542` `with_suffix(... + ".chunks.json")` |
| Manifest **shape** | README + `docs/provenance.md` | top-level **JSON array**, not an object |
| Manifest **keys** | README example | `doc_id`, `content_hash`, `chunk_id`, `heading_path`, `start`, `end`, `char_count` |
| Citation **invariant** | `tests/test_chunk.py` | `markdown[start:end] == chunk.content` and `char_count == end - start` |
| CLI flag | `--chunk` | unchanged (additive flags only) |
| Config flag | `output.chunk: bool` | unchanged (existing config files keep loading) |
| Library call | `chunk_markdown(md)` and `chunk_markdown(md, N)` | unchanged signature + semantics |

Verified in-repo callers of the chunk module (no others exist):

- `gnosis/cli/main.py::_write_chunk_manifest` — calls `chunk_markdown(markdown)`
  (no args) and `chunk_manifest(url, content_hash, chunks)`; invoked at
  `main.py:611` (single-page) and `main.py:742` (crawl).
- `tests/test_chunk.py` — imports both functions; **two tests pass
  `max_chars=300` positionally**; tests assert the `Chunk` fields, the
  `chunk_id` scheme (`c0`, `c1`, `c1.0`-style), `heading_path`, and the
  offset/char_count invariants.
- `tests/test_cli.py::test_chunk_manifest_written` — only asserts a
  `*.chunks.json` exists (shape-agnostic, but README documents the array).

Downstream RAG pipelines consume the `.chunks.json` **array**. That array shape
is the contract we are being asked to keep stable.

---

## 2. The hard compatibility invariants

These must hold after the change, verifiably:

1. **Top-level manifest is an array** of chunk objects (never `{...}` or
   `{"chunks": [...]}`).
2. **Existing six keys keep their names and meanings** — notably `char_count`
   must remain `== len(content) == end - start` (code points). It must not be
   silently redefined to bytes or tokens.
3. **`start`/`end` remain code-point offsets** into the source markdown, and
   `markdown[start:end] == chunk.content` for *every* chunk, including overlap
   chunks (overlap means two `[start, end)` windows may legitimately intersect;
   the equality invariant still holds per chunk).
4. **`chunk_id` scheme stays deterministic and hierarchical** (`c0`, `c1`,
   `c1.0`, …). Deterministic = same input + same settings → same ids.
5. **`chunk_markdown(md)` and `chunk_markdown(md, N)` keep working** with the
   current char-based, no-overlap semantics (the `tests/test_chunk.py`
   assertions must pass unmodified).
6. **`--chunk`, `output.chunk`, and the `.chunks.json` filename are unchanged.**
7. **New manifest fields are additive only** — consumers that read by key are
   unaffected; strict-schema consumers get a documented, optional superset.

---

## 3. Where `chunk-lib` breaks the contract (specific)

| # | Proposal | Breakage |
| --- | --- | --- |
| 1 | `max_chars` **removed**; signature becomes keyword-only `max_tokens` | Breaks `chunk_markdown(md, 300)` (2 tests) and any external positional caller. |
| 2 | `Chunk` made `frozen=True` and `token_count` added **without default** | Breaks positional `Chunk(...)` construction and mutation. |
| 3 | Default becomes `max_tokens=500, overlap_tokens=50` | `chunk_markdown(md)` now emits different chunks than today → silent behavior change for any external caller. |
| 4 | Manifest example shown as a **single object** | Contradicts the documented array; would break every array-reading consumer if taken literally. |

Also, two **correct but must-be-stated** behavior changes (not "back-compat
silent"):

- The single-oversized-paragraph bugfix + `min_chunk_tokens` merging + overlap
  **will change chunk count/boundaries/ids** for real documents. The claim
  "existing citations stay valid for non-overlapping cases" is only true for
  documents whose sections were already ≤ max_chars and where no trailing merge
  fires. This is fine *if* versioned and changelogged — not if sold as identical.
- `CharTokenizer(4) + max_tokens=500` is **≈2000 chars, not the old 2000-char
  ceiling** — the packing metric differs (`ceil(len/4)`) and the split rules
  differ, so "reproduces the old default" is approximate. State it as "roughly
  equivalent budget," not "identical."

---

## 4. Recommended compatibility strategy (concrete)

### 4.1 Library layer — keep the old path, add the new path

Do **not** remove `max_chars`. Make token mode opt-in:

```python
DEFAULT_MAX_CHARS = 2000  # unchanged

@dataclass
class Chunk:                      # NOT frozen
    chunk_id: str
    heading_path: list[str]
    content: str
    start: int
    end: int
    char_count: int
    token_count: int = 0          # new, defaulted (legacy path leaves 0)
    overlap_with_prev: bool = False

def chunk_markdown(
    markdown: str,
    max_chars: int | None = DEFAULT_MAX_CHARS,   # legacy positional arg, kept
    *,
    max_tokens: int | None = None,               # non-None opts into token mode
    overlap_tokens: int = 0,
    min_chunk_tokens: int | None = None,
    tokenizer: Tokenizer | None = None,
    strategy: Literal["structure", "recursive", "fixed"] = "structure",
    boundaries: tuple[tuple[str, str], ...] = DEFAULT_BOUNDARIES,
) -> list[Chunk]:
```

Semantics:

- `max_tokens is None` → **legacy char mode, byte-for-byte today's behavior**
  (including "single oversized paragraph stays one chunk") — so the existing
  `tests/test_chunk.py` and any external `chunk_markdown(md)` / `(md, N)` caller
  are untouched.
- `max_tokens is not None` → token-aware + overlap path (the `chunk-lib`
  algorithm, incl. the oversized-paragraph fix, is implemented here).
- `token_count` is populated only in token mode; `char_count` always
  `== len(content)`.

This makes `chunk_markdown` fully backward compatible while delivering the
feature. The bugfixes (`find`→arithmetic offsets, no drift) apply to **both**
paths because they are internal to `_anchor()`/offset computation and make the
`markdown[start:end] == content` invariant hold by construction rather than by
substring search.

### 4.2 Manifest — additive only, array stays

```python
def chunk_manifest(doc_id, content_hash, chunks) -> list[dict]:
    # returns the SAME array; adds two keys per entry:
    #   "token_count" (int)        — 0 in legacy mode
    #   "overlap_with_prev" (bool) — False in legacy mode
```

Keep `doc_id`, `content_hash`, `chunk_id`, `heading_path`, `start`, `end`,
`char_count` verbatim. The top-level value remains `list[dict]`. Update the
README example to show the two new keys *appended* (and keep it an array).

### 4.3 Config + CLI — additive only

- Keep `output.chunk: bool` as the **enable gate** (existing configs load
  unchanged; `load_config`'s `OutputSettings(...)` line is untouched).
- Add a new top-level **`chunking:`** section (a new `ChunkingSettings`
  dataclass + `Settings.chunking = field(default_factory=ChunkingSettings)` +
  `load_config` reads `data["chunking"]`). Name it `chunking`, not `chunk`, to
  avoid confusion with `output.chunk`. Mirrors the existing
  `downloader`/`crawler`/`render` pattern.

```yaml
chunking:
  max_tokens: 500
  overlap_tokens: 50
  min_chunk_tokens: 100
  strategy: structure          # structure | recursive | fixed
  tokenizer: char              # char | word | tiktoken
  tiktoken_encoding: cl100k_base
```

- CLI: keep `--chunk`; add `--chunk-max-tokens`, `--chunk-overlap`
  (config remains primary; flags are convenience). All additive.
- `_write_chunk_manifest(markdown, content_hash, output_path, url, *, chunking=None)`:
  default `None` keeps the legacy call, or pass `settings.chunking` to enable
  token mode. Signature stays callable by the two existing sites.

### 4.4 Versioning + changelog

- Bump **minor** (1.3.0 → 1.4.0): new feature, additive schema, additive config.
  (A major is only justified if the module default changes — which this plan
  avoids.)
- CHANGELOG must state, under **Changed**: "`--chunk` output is now
  token-aware with boundary-anchored overlap by default; the `.chunks.json`
  manifest gains additive `token_count`/`overlap_with_prev` keys; chunk ids and
  boundaries may differ from 1.3.x for documents with oversized sections."
- Document the tokenizer (default `char`) so reproducibility is explicit;
  `tiktoken` stays an optional `[chunk]` extra (no new hard dep).

---

## 5. Acceptance criteria (compat-specific, testable)

1. `chunk_markdown(md)` and `chunk_markdown(md, 300)` return byte-identical
   results to the current implementation (run the **unmodified**
   `tests/test_chunk.py` as the guard).
2. `chunk_manifest(...)` still returns a `list`, and every entry contains the
   six original keys with unchanged meanings; `char_count == end - start`.
3. Token mode is reachable only via `max_tokens=` / `chunking:` config, and in
   that mode every chunk satisfies `markdown[start:end] == content` and
   `token_count == tokenizer.count(content)`.
4. `output.chunk: true` alone (a 1.3.x config file) still loads and still writes
   `<page>.md.chunks.json` (array).
5. `--chunk` + new `--chunk-*` flags all work; `--chunk` alone remains valid.
6. Existing `.chunks.json` files from 1.3.x still parse as JSON arrays; a
   strict consumer keyed on the six fields sees no missing/renamed keys.
7. Determinism: same input + same `chunking:` config → identical manifest
   (ids, offsets, counts) across runs and across processes.

---

## 6. Bottom line for the panel

Adopt the `chunk-lib` algorithm (token budget, boundary-anchored overlap,
arithmetic offsets, oversized-paragraph fix, zero-dep default tokenizer) — but
**gate it behind `max_tokens=`** and keep the `max_chars` legacy path as the
module default. Keep the manifest an additive array, keep `--chunk`/
`output.chunk`/the filename, and call it a minor release. That is the only
shape of this feature that is consistent with gnosis's "provenance is the
contract" identity: the citation anchors (`start`/`end`/`char_count`/
`heading_path`/`chunk_id`) must not be renegotiated silently.
