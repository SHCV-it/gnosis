# Provenance

Every file gnosis writes is self-describing:

```yaml
---
title: Quickstart
url: https://docs.example.com/quickstart
fetched_at: '2026-09-02T08:41:44Z'
content_hash: 1549512c...16fd     # SHA-256 of the markdown body
bytes_sha256: 85052df6...bcb31    # SHA-256 of the response body bytes
status_code: 200
generator: gnosis/2.2.0
retention_ratio: 0.9137          # surviving text / source text (0..1)
stripped_elements: 4             # boilerplate elements removed
# low_content: true              # set when a page is likely truncated/bot-blocked
etag: '"61e917f4..."'
last_modified: Fri, 31 Jul 2026 16:07:37 GMT
---
```

Two hashes, two jobs:

- **`content_hash`** — SHA-256 of the derived Markdown (dedup/change detection).
- **`bytes_sha256`** — SHA-256 of the response body bytes, after content decoding (the *audit* hash).

The frontmatter is standard YAML, parseable by `python-frontmatter`, Jekyll,
Hugo, Obsidian, and any downstream pipeline.

## WARC + content-addressed store

`--warc` archives the raw bytes to a replayable WARC file and a
content-addressed store keyed on `bytes_sha256` — byte-identical pages are
stored once, and everything is re-fetchable and re-verifiable.

## Chunk citations

`--chunk` writes a `<page>.md.chunks.json` manifest with stable chunk ids,
heading paths, **token counts**, `chunk_sha256`, and document-relative char
offsets — anchor a citation back to the exact source span. Chunking is
token-aware: chunks never exceed a 512-token budget, with a 64-token overlap
between adjacent chunks.

## Capture quality

`retention_ratio` measures the fraction of the page's visible text that
survived conversion (0..1, computed text-vs-text, never inflated by markup).
A low ratio or a `low_content: true` flag signals a page that may be
truncated, paywalled, or bot-blocked — a persistent quality gate, not a
console warning.

## Network security (IP-pinned SSRF guard)

Before any request is made, gnosis resolves the hostname once, validates every
resolved address against a private/loopback/link-local allow-list, and dials
the **already-validated IP** — closing the DNS-rebinding TOCTOU that plagues
resolve-then-connect guards. CGNAT (`100.64.0.0/10`), 6to4, Teredo, NAT64
(`64:ff9b::/96`), and IPv4-mapped/embedded forms are blocked. Every redirect
hop is re-checked.

## Cryptographic signing (seal of origin)

`gnosis <url> --sign --sign-key key.pem` (or `$GNOSIS_SIGNING_KEY`) adds an
Ed25519 signature over a canonical manifest of the provenance fields plus the
recomputed body hash. `gnosis-keygen` generates a keypair and
`gnosis-verify file.md --public-key <key>` checks a document, exiting non-zero if the body or
provenance changed, or if the identity is not pinned (verify requires the
expected public key to establish origin). Tamper-evident, no trusted third party.

Install the optional dependency with `pip install 'gnosis-markdown[sign]'`.
