# Architecture

One canonical record flows through every stage:

```
capture ─▶ extract ─▶ provenance ─▶ archive ─▶ emit
 (fetch)    (bytes→MD)  (frontmatter)  (WARC+store)  (md/json/chunks/llms.txt)
     └─ static httpx (default) ─┘
     └─ browser backend (optional) ─┘
```

## Modules

| Module | Responsibility |
| --- | --- |
| `core/downloader.py` | Async httpx fetch, retries, rate limit, auth, robots, SSRF guard |
| `core/converter.py` | HTML → clean Markdown (boilerplate stripping, GFM tables, metadata) |
| `core/provenance.py` | YAML frontmatter, `content_hash` + `bytes_sha256` |
| `core/archive.py` | WARC + content-addressed store |
| `core/crawler.py` | BFS crawl with scope, concurrency, and resume (checkpoint dedup) |
| `core/robots.py` | robots.txt (RFC 9309) + Crawl-delay |
| `core/network.py` | SSRF / private-network guard |
| `core/render.py` | Optional JS renderer (sidecar subprocess) |
| `core/chunk.py` | Heading-scoped chunking with citation offsets |
| `core/checkpoint.py` | Resumable-crawl persistence |
| `core/llms.py` | `llms.txt` emission + sitemap discovery |
| `bench.py` | `gnosis-bench` scorecard |
| `integrations/documents.py` | `gnosis-doc` (MarkItDown, lazy import) |
| `integrations/qmd.py` | Optional QMD vector-DB indexing |

## Principles

- **Static-first.** The default path is a lightweight `httpx` fetch. Heavy
  dependencies (torch, markitdown, a JS renderer binary) are optional extras
  behind a lazy import or a sidecar process.
- **Provenance over polish.** Markdown is a *projection*; the raw bytes + WARC
  are the source of truth. Hash the bytes, not the text.
- **Secure by default.** SSRF guard on every request and redirect hop, secrets
  via `${ENV_VAR}` only, robots.txt respected.
