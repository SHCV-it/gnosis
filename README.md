# gnosis-markdown — Web to Markdown scraper with byte-level SHA-256 provenance

**Prove what you fetched — and that it's unchanged.**

*Web → clean, RAG-ready Markdown — with verifiable provenance stamped into every file.*

gnosis-markdown is an open-source **Python web-to-Markdown scraper and crawler** for
LLM/RAG pipelines: it converts HTML to clean Markdown and stamps every file with
verifiable SHA-256, WARC, and Ed25519 provenance.

**Start now:**

```bash
pip install gnosis-markdown && gnosis https://docs.python.org/3/tutorial/
```

> **Markdown is a projection; the raw bytes + WARC are the source of truth.**

For **RAG engineers**, **compliance & data-governance teams**, and
**security-sensitive researchers** who need to *prove* — not just assume —
what was fetched and that it hasn't changed, gnosis-markdown fetches and crawls any
page into LLM-ready Markdown while stamping every file with byte-level SHA-256, WARC
archival, and Ed25519 signatures you can verify independently.

<p align="center">
  <a href="https://pypi.org/project/gnosis-markdown/"><img alt="PyPI Version" src="https://img.shields.io/pypi/v/gnosis-markdown?color=blue"></a>
  <a href="https://pypi.org/project/gnosis-markdown/"><img alt="Python Versions" src="https://img.shields.io/pypi/pyversions/gnosis-markdown?color=blue"></a>
  <a href="https://github.com/SHCV-it/gnosis/actions"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/SHCV-it/gnosis/ci.yml?branch=main"></a>
  <a href="https://shcv-it.github.io/gnosis/"><img alt="Docs" src="https://img.shields.io/badge/docs-shcv--it.github.io-blue"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="https://doi.org/10.5281/zenodo.22276101"><img alt="DOI" src="https://zenodo.org/badge/DOI/10.5281/zenodo.22276101.svg"></a>
  <a href="https://glama.ai/mcp/servers/SHCV-it/gnosis"><img alt="MCP server on Glama" src="https://glama.ai/mcp/servers/SHCV-it/gnosis/badges/score.svg"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/SHCV-it/gnosis/main/docs/demo.gif" alt="gnosis-markdown converting a web page to RAG-ready Markdown with provenance" width="720">
</p>

## Quick start: scrape any page to Markdown

```bash
pip install gnosis-markdown

# One page → one markdown file (written to ./ by default; use -o to change it)
gnosis https://docs.python.org/3/tutorial/

# Crawl an entire section
gnosis https://docs.python.org/3/tutorial/ --all -o ./python-docs/

# Archive the raw bytes to WARC + a content-addressed store, and sign the record
pip install 'gnosis-markdown[sign]'   # signing needs the [sign] extra
gnosis https://docs.python.org/3/tutorial/ --warc --sign --sign-key key.pem

# Emit per-chunk citation manifests for RAG
gnosis https://example.com --chunk

# Export with provenance (JSON / JSONL / Parquet)
gnosis https://example.com --format json

# Evaluate yourself against a corpus (one URL per line)
printf 'https://docs.python.org/3/\nhttps://example.com/\n' > urls.txt
gnosis-bench --urls urls.txt

# Convert a PDF/Office doc to Markdown (pip install gnosis-markdown[docs])
gnosis-doc report.pdf -o report.md
```

**JS rendering** is opt-in via a sidecar binary (default `obscura`); install the
[Obscura](https://github.com/h4ckf0r0day/obscura) binary, then
`gnosis https://my-spa.example --render` (or set `render.engine` in config). Obscura is
a third-party project outside gnosis's audit scope — pin a version and review it before use.

## Why gnosis-markdown — web to Markdown with provenance

**The provenance-first web-to-Markdown layer for LLM pipelines — not another scraper.**

You can scrape the web with a dozen tools. Of the four compared here, only one ships
provenance as a first-class, in-tree feature. gnosis-markdown turns every fetch into an
auditable **Capture Record**: hash the bytes, archive the raw response, record the
consent signals, and sign the result — so the document in your RAG index is traceable
to the decoded response body bytes.

Firecrawl, Crawl4AI and Jina Reader win on speed, scale and hosting.
gnosis-markdown doesn't compete there — it wins on **auditability**, the one axis none
of them ship as a first-class feature.

> **Known limitations, stated plainly:** `retention_ratio` measures *how much*
> text survived extraction, not *which* text (a single dropped table in a long
> document barely moves it — see §4.4 of the spec). JS rendering is opt-in via
> a sidecar. The SSRF guard covers direct connections, not proxies. Full
> disclosure in [SECURITY.md](https://github.com/SHCV-it/gnosis/blob/main/SECURITY.md).

## Verify provenance yourself (reproduce the hash)

The provenance claim is the product. After a fetch:

```bash
gnosis https://docs.python.org/3/tutorial/ -o out/ --warc

# One command: extract the hash from the frontmatter and integrity-check the archived body blob.
# macOS/BSD: replace `sha256sum` with `shasum -a 256`
h=$(sed -n 's/^bytes_sha256: *//p' out/*.md | head -1); printf '%s  %s\n' "$h" "out/.gnosis-store/$h" | sha256sum -c -
# prints: <hash>: OK
```

With `--warc`, every fetched file is re-fetchable and re-verifiable — the digest lives
in the frontmatter, so no sidecar index is needed to re-verify. Without `--warc`, the
frontmatter hash still records provenance, but the raw bytes are not retained.

**A real, committed example:** [`docs/examples/example.com.md`](https://github.com/SHCV-it/gnosis/blob/main/docs/examples/example.com.md) was fetched live with `--warc` — its `bytes_sha256` (`ff67a9d7…`), `content_hash`, and `fetched_at` are real. The raw bytes are archived at `docs/examples/archive.warc.gz`, and the content-addressed blob lives at `docs/examples/.gnosis-store/<bytes_sha256>`. Verify it with no network access:

```bash
h=$(sed -n 's/^bytes_sha256: *//p' docs/examples/example.com.md); printf '%s  %s\n' "$h" "docs/examples/.gnosis-store/$h" | sha256sum -c -
```

Reproducible benchmark evidence: see [BENCHMARKS.md](https://github.com/SHCV-it/gnosis/blob/main/BENCHMARKS.md).

## gnosis-markdown vs Firecrawl, Crawl4AI, Jina Reader

This table covers only the audit/provenance surface — not speed, scale, or hosting.

| Audit-surface capability | gnosis-markdown | Firecrawl | Crawl4AI | Jina Reader |
| --- | --- | --- | --- | --- |
| `bytes_sha256` — SHA-256 of the response body bytes | ✅ | ❌ | ❌ | ❌ |
| `content_hash` — SHA-256 of the derived Markdown | ✅ | ⚠️ | ⚠️ | ❌ |
| WARC archival + content-addressed store (replayable, ISO 28500) | ✅ | ❌ | ❌ | ❌ |
| Ed25519 seal of origin (sign + pinned-key verify) | ✅ | ❌ | ❌ | ❌ |
| ai.txt / llms.txt consent recording per fetch | ✅ | ❌ | ❌ | ❌ |
| Deny-overrides compliance policy engine + `--profile` presets | ✅ | ❌ | ❌ | ❌ |
| IP-pinned SSRF guard (closes DNS-rebinding TOCTOU) | ✅ | ➖ | ❌ | ➖ |
| Per-job Data Card (`data-card.json`) | ✅ | ❌ | ❌ | ❌ |
| Versioned, machine-readable Capture Record spec | ✅ | ❌ | ❌ | ❌ |

**Legend:** ✅ first-class, shipped in-tree and verifiable · ⚠️ partial / not the
same thing · ❌ not offered as a documented feature · ➖ present but not audited against
these criteria, or server-side and not third-party verifiable.

*As of September 2026. gnosis-markdown claims are verifiable against this
repository (`--sign`, `--warc`, `--profile`, `gnosis-keygen`, `gnosis-verify`).
Competitor columns reflect their public docs at time of writing — re-verify
each project against its own repository before relying on this table.
Jina Reader is a hosted service whose server-side SSRF behavior is not verifiable by a
third party. Firecrawl is open-source and self-hostable, so its `➖` marks that we did
not audit it against these criteria, not that it is opaque.*

**Sources (verified 2026-09-07):** gnosis-markdown — [328-test suite](https://github.com/SHCV-it/gnosis/tree/main/tests)
and the [Capture Record spec](https://github.com/SHCV-it/gnosis/blob/main/docs/capture-record-spec.md) · Firecrawl —
[docs.firecrawl.dev](https://docs.firecrawl.dev) · Crawl4AI —
[github.com/unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) · Jina Reader —
[jina.ai/reader](https://jina.ai/reader).

## Features

### Provenance & audit — the moat

- **`bytes_sha256`** — SHA-256 of the response body bytes (after HTTP content
  decoding — the decoded body, not wire/transfer bytes). You hash the bytes, not the derived text.
- **`content_hash`** — SHA-256 of the emitted Markdown, so transforms are
  auditable too.
- **WARC archival** (`--warc`) — WARC-grade evidence, replayable via any ISO 28500 WARC replayer (e.g. pywb), plus
  a content-addressed store keyed on `bytes_sha256`. Every file is re-fetchable
  and re-verifiable — the digest lives in the file, not a database.
- **Ed25519 signing — seal of origin** — `--sign` cryptographically signs each
  record; `gnosis-keygen` mints keypairs and `gnosis-verify` checks them against
  a pinned key. Prove a document came from a capture you made, untouched.
- **Data cards** — every scrape/crawl job writes a `data-card.json`: sources,
  sizes, licenses encountered, ai.txt/llms.txt coverage, and compliance
  decisions — one artifact an auditor reads instead of opening every file.

### Consent & compliance policy

- **ai.txt / llms.txt consent recording** — a host's `ai.txt` directives and
  `llms.txt` presence are captured into the frontmatter of every affected file.
- **Compliance policy engine** — per-page `allow_if` / `deny_if` rules with
  **deny-overrides** semantics, matched on license, ai.txt directives, and URL
  path. Decisions are recorded in the frontmatter and data card, not just
  applied.
- **`--profile` presets** — `strict-optout` (block training/data opt-outs and
  `Disallow:` paths) and `open-only` (permissive/open licenses only).

> **ai.txt is advisory, not enforced by default.** gnosis *records* a site's
> ai.txt opt-out but does not, by default, refuse to scrape. To stop scraping
> at opt-outs, use `--profile strict-optout` or an explicit `deny_if` rule.
> "We record the opt-out and scrape anyway" is exactly the behavior a regulator
> will ask about — decide it deliberately.

### Security

- **IP-pinned SSRF guard** — blocks loopback, RFC1918, link-local, multicast,
  CGNAT/6to4/Teredo/NAT64, and every redirect hop — closing the DNS-rebinding
  TOCTOU by resolving once, validating every address, and dialing only pinned
  IPs (TLS SNI still uses the hostname, so pinning never weakens TLS).
- **robots.txt + politeness** respected (per-host rate limiting, `Crawl-delay`
  capped), fail-open on errors.
- Auth/custom headers are sent only to the original origin — never replayed to
  cross-origin redirect targets.
- Secrets via `${ENV_VAR}` — keep credentials out of config files and shell history.

### Extraction & output

- Clean, main-content Markdown with valid GFM tables, metadata extraction, and
  boilerplate stripping — plus a `retention_ratio` / `stripped_elements` /
  `low_content` audit trail over the transform itself.
- **Token-aware chunking** (`--chunk`) — stable chunk IDs, heading paths, and
  exact byte offsets in a per-page `.chunks.json` citation manifest.
- **Multi-format export** — `--format json|jsonl|parquet`, each record carrying
  full provenance.
- **`llms.txt` / `llms-full.txt` emission** on every crawl.

### Crawling at scale

- **Incremental crawl + conditional GET** — `If-None-Match` / `304` skip
  unchanged downloads; a hash-native checkpoint makes `--all` **resumable**,
  growing past `max_pages` across runs.

### Integrations

- **MCP server** (`gnosis-mcp`) — expose gnosis as an MCP `fetch_and_convert`
  tool that returns provenance-stamped Markdown (`[mcp]` extra).
- **LlamaIndex reader** and **LangChain document loader** — return provenance-
  stamped `Document`s (`[llamaindex]` / `[langchain]` extras).
- **Plugin hooks** — `pre_fetch` / `post_fetch` / `post_process` for custom
  auth, filtering, and post-processing.
- **Companion CLIs** — `gnosis-bench` (reproducible scorecard), `gnosis-doc`
  (PDF/Office → Markdown), `gnosis-keygen` / `gnosis-verify` (signing).

## Provenance: the contract

The full machine-readable contract — every field, its exact semantics, and
conformance rules — is in the [Capture Record Specification](https://github.com/SHCV-it/gnosis/blob/main/docs/capture-record-spec.md).

```yaml
---
title: Quickstart
url: https://docs.example.com/quickstart
fetched_at: '2026-09-02T08:41:44Z'
content_hash: 1549512c...16fd     # SHA-256 of the markdown body
bytes_sha256: 85052df6...bcb31    # SHA-256 of the response body bytes
status_code: 200
generator: gnosis/2.4.2
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
| `--sign` | Cryptographically sign the output (Ed25519 seal of origin) |
| `--sign-key FILE` | Ed25519 private key (PEM) for `--sign` (default `$GNOSIS_SIGNING_KEY`) |
| `--format json\|jsonl\|parquet` | Also export documents (with provenance) |
| `--profile NAME` | Compliance preset: `strict-optout` / `open-only` |

Also available: **`gnosis-bench`** (reproducible scorecard), **`gnosis-doc`**
(document → Markdown), **`gnosis-keygen`** (generate a signing keypair),
**`gnosis-verify`** (verify a signed document — pass `--public-key` to pin the
producer identity), and **`gnosis-mcp`** (MCP server).

## Installation

```bash
pip install gnosis-markdown                  # core
pip install 'gnosis-markdown[sign]'          # Ed25519 signing (cryptography)
pip install 'gnosis-markdown[parquet]'       # Parquet export (pyarrow)
pip install 'gnosis-markdown[mcp]'           # MCP server
pip install 'gnosis-markdown[llamaindex]'    # LlamaIndex reader
pip install 'gnosis-markdown[langchain]'     # LangChain loader
pip install 'gnosis-markdown[docs]'          # document conversion (MarkItDown)
pip install 'gnosis-markdown[qmd]'           # QMD vector-DB indexing
```

Requires **Python 3.9+** (the `mcp`, `docs`, `qmd`, `llamaindex`, and `langchain` extras need 3.10+). See
[`gnosis/config/default.yaml`](https://github.com/SHCV-it/gnosis/blob/main/gnosis/config/default.yaml) for the full
configuration reference.

## Background

> **It started with an audit.** I tested my own scraper against a page I'd
> written, and its "completeness" metric reported **106% retention** on a
> document that had lost a third of its text. The number was arithmetically
> valid; every test was green — the metric was certifying garbage. The fix — and
> the open problem it exposed — are in the
> [self-audit](https://github.com/SHCV-it/gnosis/blob/main/docs/self-audit.md) and
> [spec §4.4](https://github.com/SHCV-it/gnosis/blob/main/docs/capture-record-spec.md).

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
