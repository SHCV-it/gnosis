# Gnosis — Web Scraping → Markdown for LLMs (RAG-ready, byte-level provenance)

<p align="center">
  <strong>The auditable web scraper that turns the internet into LLM-ready knowledge.</strong><br>
  Open-source · Self-hostable · Byte-level SHA-256 · WARC archival · MIT
</p>

<p align="center">
  <a href="https://pypi.org/project/gnosis-markdown/"><img alt="PyPI Version" src="https://img.shields.io/pypi/v/gnosis-markdown?color=blue"></a>
  <a href="https://pypi.org/project/gnosis-markdown/"><img alt="Python Versions" src="https://img.shields.io/pypi/pyversions/gnosis-markdown?color=blue"></a>
  <a href="https://github.com/SHCV-it/gnosis/actions"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/SHCV-it/gnosis/ci.yml?branch=main"></a>
  <a href="https://shcv-it.github.io/gnosis/"><img alt="Docs" src="https://img.shields.io/badge/docs-shcv--it.github.io-blue"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

**Gnosis** is an open-source web scraper and crawler that downloads websites
(and documents) and converts them into clean, LLM-friendly Markdown for RAG
pipelines and knowledge bases — with a **YAML provenance block on every file**
recording where the bytes came from, when they were fetched, and how to verify
them. It is the *auditable* web-to-Markdown converter.

> **Markdown is a projection; the raw bytes + WARC are the source of truth.**
> Unlike Firecrawl, Crawl4AI, or Jina Reader, gnosis ships byte-level SHA-256
> and WARC-grade evidence out of the box.

<p align="center">
  <img src="https://raw.githubusercontent.com/SHCV-it/gnosis/main/docs/demo.gif" alt="gnosis in action" width="720">
</p>

## Why Gnosis

| Feature | Gnosis | Firecrawl | Crawl4AI | Jina Reader |
| --- | --- | --- | --- | --- |
| Clean Markdown | ✅ | ✅ | ✅ | ✅ |
| JS rendering | ✅ opt-in | ✅ | ✅ | ✅ |
| **Byte-level SHA-256 provenance** | ✅ | ❌ | ❌ | ❌ |
| **WARC archival (replay via pywb)** | ✅ | ❌ | ❌ | ❌ |
| **Built-in SSRF / private-network guard** | ✅ | ⚠️ | ❌ | ❌ |
| robots.txt + politeness | ✅ | ⚠️ | ⚠️ | ❌ |
| Self-hostable / offline | ✅ | ✅ | ✅ | ✅ |
| License | MIT | AGPL-3.0 | Apache-2.0 | MIT |

✅ yes · ⚠️ partial · ❌ no — *as of September 2026; verify each project's
current capabilities and license against its own repository.*

## Verify it yourself

The provenance claim is the product. After a fetch:

```bash
gnosis https://docs.python.org/3/tutorial/ -o out/ --warc

# The frontmatter's bytes_sha256 is the SHA-256 of the raw response:
shasum -a 256 out/.gnosis-store/<bytes_sha256>   # matches the hash in the .md
```

Every markdown file is re-fetchable and re-verifiable — no sidecar bookkeeping.

Reproducible benchmark evidence: see [BENCHMARKS.md](https://github.com/SHCV-it/gnosis/blob/main/BENCHMARKS.md).

## Quick start

Requires **Python 3.12+**.

```bash
pip install gnosis-markdown

# One page → one markdown file (written to ./ by default; use -o to change it)
gnosis https://docs.python.org/3/tutorial/

# Crawl an entire section
gnosis https://docs.python.org/3/tutorial/ --all -o ./python-docs/

# Archive the raw bytes to WARC + a content-addressed store
gnosis https://docs.python.org/3/tutorial/ --warc

# Emit per-chunk citation manifests for RAG
gnosis https://docs.example.com --chunk

# Evaluate yourself against a corpus (one URL per line)
printf 'https://docs.python.org/3/\nhttps://example.com/\n' > urls.txt
gnosis-bench --urls urls.txt

# Convert a PDF/Office doc to Markdown (pip install gnosis-markdown[docs])
gnosis-doc report.pdf -o report.md
```

**JS rendering** is opt-in via a sidecar binary (default `obscura`); install the
[Obscura](https://github.com/h4ckf0r0day/obscura) binary, then
`gnosis https://my-spa.example --render` (or set `render.engine` in config).

## Features

**Provenance & audit (the moat)**
- YAML frontmatter on every file: `url`, `fetched_at` (UTC), `status_code`,
  `etag`, `last_modified`, `generator`, and `requested_url` (when redirected).
- **`content_hash`** (SHA-256 of the markdown) *and* **`bytes_sha256`** (SHA-256
  of the raw response-body bytes) — hash the bytes, not the derived text.
- **WARC export** (`--warc`) + a content-addressed store keyed on `bytes_sha256`.
- `llms.txt` + `llms-full.txt` emitted on every crawl.

**Fetching & access**
- Static-first async fetch (`httpx`); optional JS rendering via a sidecar binary.
- **robots.txt** respected (with `Crawl-delay` politeness); fail-open on errors.
- **SSRF / private-network guard**: blocks loopback/RFC1918/link-local/multicast
  and every redirect hop (opt out with `--allow-private-network`).
- Auth: Bearer, HTTP Basic (Confluence PAT), and custom headers. Reference
  secrets as `${ENV_VAR}` (supported in config and `--header` values) and keep
  them out of config files and shell history.

**Extraction & output**
- Main-content detection + class-word boilerplate stripping.
- Valid GFM tables (multi-para cells, pipe escaping, sticky-header dedup).
- Metadata extraction (title/author/language/description/Open Graph).
- **Chunking** (`--chunk`) with stable chunk ids + heading paths + offsets.
- Resumable crawls (`--all`) via a content-hash checkpoint.

### Chunk manifest example

`gnosis https://docs.example.com --chunk` writes `<page>.md.chunks.json`:

```json
[
  {
    "doc_id": "https://docs.example.com",
    "content_hash": "1549512c...",
    "chunk_id": "c0",
    "heading_path": ["Title"],
    "start": 0,
    "end": 812,
    "char_count": 812
  }
]
```

## Provenance: the contract

The full machine-readable contract — every field, its exact semantics, and conformance rules — is in the [Capture Record Specification](https://github.com/SHCV-it/gnosis/blob/main/docs/capture-record-spec.md).

```yaml
---
title: Quickstart
url: https://docs.example.com/quickstart
fetched_at: '2026-09-02T08:41:44Z'
content_hash: 1549512c...16fd     # SHA-256 of the markdown body
bytes_sha256: 85052df6...bcb31    # SHA-256 of the raw response bytes
status_code: 200
generator: gnosis/1.2.1
etag: '"61e917f4..."'
last_modified: Fri, 31 Jul 2026 16:07:37 GMT
---
```

Standard YAML, parseable by `python-frontmatter`, Jekyll, Hugo, Obsidian, and
any downstream pipeline. Opt out with `--no-frontmatter`.

## CLI reference

```
gnosis URL [OPTIONS]
```

| Flag | Description |
| --- | --- |
| `-a, --all` | Crawl all child pages under the URL path |
| `-n, --dry-run` | Discover and count pages only (requires `--all`) |
| `-o, --output DIR` | Output directory (default `./`) |
| `-c, --config FILE` | YAML configuration file |
| `-f, --overwrite` | Overwrite existing files |
| `-q, --quiet` / `-v, --verbose` | Suppress / show diagnostics |
| `--no-frontmatter` | Write bare markdown (no provenance) |
| `--frontmatter KEY: VALUE` | Extra constant frontmatter field (repeatable) |
| `--header NAME: VALUE` | Extra request header (repeatable) |
| `--bearer-token-env VAR` | Bearer token from environment variable |
| `--basic-user USER` | HTTP Basic username (requires `--basic-token-env`) |
| `--basic-token-env VAR` | HTTP Basic password/token from environment variable |
| `--allow-private-network` | Bypass the SSRF guard (opt-in) |
| `--warc` | Archive raw bytes to WARC + content-addressed store |
| `--render` | Render pages with the configured JS renderer |
| `--chunk` | Write per-chunk citation manifests (`.chunks.json`) |
| `--sitemap` | Treat URL as a sitemap.xml and list its page URLs |
| `--qmd-index` | Index output into QMD (requires `[qmd]` extra) |

Also available: **`gnosis-bench`** (reproducible scorecard) and **`gnosis-doc`**
(document → Markdown).

## Installation

```bash
pip install gnosis-markdown          # core
pip install gnosis-markdown[qmd]     # optional QMD vector-DB indexing
pip install gnosis-markdown[docs]    # optional document conversion (MarkItDown)
```

Requires **Python 3.12+**. See
[`gnosis/config/default.yaml`](https://github.com/SHCV-it/gnosis/blob/main/gnosis/config/default.yaml) for the full
configuration reference.

## Development

```bash
git clone https://github.com/SHCV-it/gnosis.git
cd gnosis
pip install -e '.[test]'
python -m pytest tests/ -q          # offline suite (localhost fixtures)
```

## Contributing

Contributions are welcome — open an issue first to discuss. Report security
issues privately (see [SECURITY](https://github.com/SHCV-it/gnosis/blob/main/SECURITY.md)). See
[ROADMAP.md](https://github.com/SHCV-it/gnosis/blob/main/ROADMAP.md) for the project plan.

## License

MIT — see [LICENSE](https://github.com/SHCV-it/gnosis/blob/main/LICENSE).

**Authors:** Steffen Hoehne & Ali Zahid Raja, [SHCV.IT](https://shcv.it)
