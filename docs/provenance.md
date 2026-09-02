# Provenance

Every file gnosis writes is self-describing:

```yaml
---
title: Quickstart
url: https://docs.example.com/quickstart
fetched_at: '2026-09-02T08:41:44Z'
content_hash: 1549512c...16fd     # SHA-256 of the markdown body
bytes_sha256: 85052df6...bcb31    # SHA-256 of the raw response bytes
status_code: 200
generator: gnosis/1.2.0
etag: '"61e917f4..."'
last_modified: Fri, 31 Jul 2026 16:07:37 GMT
---
```

Two hashes, two jobs:

- **`content_hash`** — SHA-256 of the derived Markdown (dedup/change detection).
- **`bytes_sha256`** — SHA-256 of the raw wire bytes (the *audit* hash).

The frontmatter is standard YAML, parseable by `python-frontmatter`, Jekyll,
Hugo, Obsidian, and any downstream pipeline.

## WARC + content-addressed store

`--warc` archives the raw bytes to a replayable WARC file and a
content-addressed store keyed on `bytes_sha256` — byte-identical pages are
stored once, and everything is re-fetchable and re-verifiable.

## Chunk citations

`--chunk` writes a `<page>.md.chunks.json` manifest with stable chunk ids,
heading paths, and document-relative char offsets — anchor a citation back to
the exact source span.
