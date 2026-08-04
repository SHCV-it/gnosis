# Gnosis

<p align="center">
  <strong>Website → clean, provenance-stamped Markdown.</strong><br>
  <em>Built for LLM knowledge bases, documentation pipelines, and audit-ready content archives.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/gnosis-markdown/"><img alt="PyPI" src="https://img.shields.io/pypi/v/gnosis-markdown?color=blue"></a>
  <a href="https://pypi.org/project/gnosis-markdown/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/gnosis-markdown?color=blue"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

---

Point gnosis at a URL and get clean, LLM-friendly Markdown files with a **YAML
provenance frontmatter block** on every file — recording exactly where the
content came from, when it was fetched, and how to verify it. No external
bookkeeping, no hidden state. Every file is self-describing.

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Provenance: the contract](#provenance-the-contract)
- [Authenticated fetching](#authenticated-fetching)
- [CLI reference](#cli-reference)
- [Configuration reference](#configuration-reference)
- [Exit codes](#exit-codes)
- [How clean is the output?](#how-clean-is-the-output)
- [Development & testing](#development--testing)
- [License](#license)

## Features

| Feature | Description |
|---|---|
| **Single page or full site** | One URL, or crawl every page under a path with `--all` |
| **Provenance frontmatter** | Every file records `url`, `fetched_at` (UTC), SHA-256 `content_hash`, `status_code`, page metadata (title/author/language), and caching headers when the server sends them |
| **Authentication built-in** | Bearer tokens, HTTP Basic (Confluence Cloud API tokens), or arbitrary headers — secrets **always** from environment variables |
| **Clean extraction** | Main-content detection with ordered selectors, class-word boilerplate stripping (sidebars, breadcrumbs, cookie banners, permalink anchors), and framework-aware fixes for Confluence, Sphinx/RTD, and GitHub-style pages |
| **Valid GFM tables** | Multi-paragraph cells joined with `<br>`, pipes escaped, sticky-header clone tables removed — tables survive ingestion |
| **Scalable crawling** | Configurable concurrent fetches, politeness delay, retries with backoff, robots-aware |
| **Scheduler-friendly** | Headless CLI, meaningful exit codes, JSON crawl manifest — drops into cron, n8n, Airflow, CI |
| **Metadata extraction** | Title (entity-unescaped), author, language, description, Open Graph fields |
| **Optional QMD integration** | Index output into a QMD knowledge base with local-LLM context generation (`pip install gnosis[qmd]`) |

## Installation

```bash
pip install gnosis-markdown
```

Requires **Python 3.12+**. Optional QMD integration (pulls torch + transformers):

```bash
pip install gnosis-markdown[qmd]
```

### From source

```bash
git clone https://github.com/SHCV-it/gnosis.git
cd gnosis
pip install -e .          # core
pip install -e .[qmd]     # with QMD integration
```

## Quick start

```bash
# One page → one markdown file with provenance
gnosis https://docs.python.org/3/tutorial/

# Crawl an entire section of a docs site
gnosis https://docs.python.org/3/tutorial/ --all -o ./python-docs/

# Preview how many pages would be crawled (no downloads)
gnosis https://docs.python.org/3/tutorial/ --all --dry-run

# Faster crawl with parallel fetches
gnosis https://docs.example.com/ --all --config myconfig.yaml
```

## Provenance: the contract

Every file gnosis writes is self-describing. Default frontmatter:

```yaml
---
title: Quickstart — Trafilatura 2.2.0 documentation
url: https://trafilatura.readthedocs.io/en/latest/quickstart.html
fetched_at: '2026-08-04T10:24:17Z'
content_hash: 1549512c...16fd
status_code: 200
generator: gnosis/1.1.0
language: en
etag: '"61e917f4cd107c3bce6182b633819fcf"'
last_modified: Fri, 31 Jul 2026 16:07:37 GMT
---
```

| Field | Required | Description |
|---|---|---|
| `title` | Always | Page title (from `og:title` or `<title>`, HTML entities unescaped) |
| `url` | Always | Final URL after redirects (`requested_url` added if it differs) |
| `fetched_at` | Always | UTC fetch timestamp, ISO 8601 |
| `content_hash` | Always | SHA-256 of the markdown body — use for dedup/change detection |
| `status_code` | Always | HTTP status of the final response |
| `generator` | Always | Gnosis version that produced this file |
| `language` | If present | From `<html lang>` or `og:locale` |
| `author` | If present | From `<meta name=author>`, `article:author`, or `dc.creator` |
| `description` | If present | From `<meta name=description>` or `og:description` |
| `site_name` | If present | From `og:site_name` |
| `published_time` | If present | From `article:published_time` |
| `modified_time` | If present | From `article:modified_time` |
| `etag` | If sent | Response `ETag` header |
| `last_modified` | If sent | Response `Last-Modified` header |
| `requested_url` | If redirected | Original URL before redirects |

Add your own constant fields per run (`--frontmatter`) or per config
(`output.frontmatter_extra`) — custom keys never override the core provenance
fields above:

```bash
gnosis https://example.com/docs --frontmatter 'tags: [customs, passar]' --frontmatter 'owner: kb-team'
```

The frontmatter is standard YAML between `---` fences: parseable by
python-frontmatter, Jekyll, Hugo, Obsidian, and any downstream knowledge
pipeline.

Opt out per run with `--no-frontmatter` or globally in config:
```yaml
output:
  frontmatter: false
```

## Authenticated fetching

Secrets are read from **environment variables only**. They are never passed as
plain CLI arguments (which leak into shell history and process tables) and
never committed in config files.

### Confluence Cloud with a Personal Access Token

```bash
# Set up a PAT at https://id.atlassian.com/manage/api-tokens
export CONFLUENCE_PAT="your-api-token"

gnosis "https://your-domain.atlassian.net/wiki/spaces/SPACE/pages/PAGE_ID" \
  --basic-user you@example.com \
  --basic-token-env CONFLUENCE_PAT
```

### Bearer token (authenticated API docs, internal tools)

```bash
export MY_API_TOKEN="..."
gnosis https://internal.example.com/docs --bearer-token-env MY_API_TOKEN
```

### Custom headers

```bash
gnosis https://example.com --header "X-API-Key: ${MY_KEY}" --header "X-Team: docs"
```

### Via config file (multi-run / CI)

```yaml
downloader:
  auth:
    type: basic                      # bearer | basic | header
    username: "you@example.com"
    password: "${CONFLUENCE_PAT}"    # ${ENV_VAR} expanded at load time
```

## CLI reference

```
gnosis URL [OPTIONS]
```

| Flag | Description |
|---|---|
| `-a, --all` | Crawl all child pages under the URL path |
| `-n, --dry-run` | Discover and count pages only (requires `--all`) |
| `-o, --output DIR` | Output directory (default: `./`) |
| `-c, --config FILE` | Path to YAML configuration file |
| `-f, --overwrite` | Overwrite existing output files |
| `-q, --quiet` | Suppress progress output |
| `-v, --verbose` | Show detailed conversion diagnostics |
| `--no-frontmatter` | Write bare markdown without provenance block |
| `--frontmatter KEY: VALUE` | Extra constant frontmatter field (repeatable) |
| `--header NAME: VALUE` | Extra request header, `${ENV_VAR}` expanded (repeatable) |
| `--bearer-token-env VAR` | Bearer token from environment variable |
| `--basic-user USER` | HTTP Basic username (requires `--basic-token-env`) |
| `--basic-token-env VAR` | HTTP Basic password/token from environment variable |
| `--qmd-index` | Index output into QMD (requires `[qmd]` extra) |

## Configuration reference

Copy [`config/default.yaml`](config/default.yaml) and pass it with `-c`.
Full reference:

```yaml
# ── Downloader ────────────────────────────
downloader:
  timeout: 30                # Request timeout (seconds)
  retries: 3                 # Retries on 5xx / network errors
  user_agent: "Gnosis/1.1"   # User-Agent header
  rate_limit_ms: 500          # Minimum delay between requests (0 = no limit)
  respect_robots: true        # Obey robots.txt (future)
  headers: {}                 # Extra HTTP headers (${ENV_VAR} expanded)
  auth:                       # Optional: bearer | basic | header
    type: bearer
    token: "${MY_API_TOKEN}"

# ── Crawler ───────────────────────────────
crawler:
  max_depth: 10              # Crawl depth from seed URL
  max_pages: 500             # Stop after this many pages
  concurrent_requests: 5     # Parallel fetch batch size (1 = sequential)

# ── Converter ─────────────────────────────
converter:
  excluded_tags: [...]        # HTML tags stripped before conversion
  content_selectors: [...]    # Tried in order; first match ≥ 200 chars wins
  strip_classes: [...]        # Exact class-token matches to remove
  strip_class_words: [...]    # Word-level matches inside class names
  include_images: true        # Emit <img> as ![alt](src)
  absolute_urls: true         # Resolve relative links to absolute URLs

# ── Output ─────────────────────────────────
output:
  directory: "./"             # Where .md files go
  overwrite: false            # Skip existing files unless true
  extension: ".md"            # Output file extension
  frontmatter: true           # Write YAML provenance block
  frontmatter_extra: {}       # Constant fields added to every file

# ── QMD (optional) ──────────────────────────
qmd:
  enabled: false              # Enable QMD knowledge base indexing
  llm_model: "Qwen/Qwen3-0.6B"  # HuggingFace model for context generation
  llm_device: "cpu"           # cpu | cuda | auto
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (crawl mode: at least one page saved) |
| `1` | Failure — download error, file exists without `-f`, nothing saved, bad flags |
| `130` | Interrupted (Ctrl-C) |

In `--all` mode a `_manifest.json` is written to the output directory listing
every page with `url`, `file`, `content_hash`, `fetched_at`, `status_code`, and
`title` — ready for schedulers and downstream audit.

## How clean is the output?

Gnosis is opinionated about boilerplate. By default it:

- **strips** script/style/nav/footer/aside/form/template tags and HTML comments
  (including Confluence's `<!-- data-loadable-begin=... -->` SSR markers)
- **removes** elements matching exact `strip_classes` tokens AND boilerplate
  *words* (`sidebar`, `toc`, `breadcrumb`, `cookie`, `headerlink`, `sourcelink`, …)
  inside namespaced class names — `bd-sidebar-primary` is gone, but `research-content`
  stays
- **cleans** permalink anchors from headings (`# Quickstart#` → `# Quickstart`)
- **picks** the main content by precedence-ordered selectors
  (`.markdown-body`, `.ak-renderer-document`, `.wiki-content`, … before `main`/`#content`)
- **converts** tables to valid GFM: multi-line cells joined with `<br>`, `|`
  escaped, duplicate/sticky-header rows removed
- **resolves** relative links to absolute URLs; skips `data:`-URI images
  (spacers/tracking pixels)
- **unescapes** HTML entities in titles (`&#8212;` → `—`)

Everything is configurable — see [`config/default.yaml`](config/default.yaml).

## Development & testing

```bash
git clone https://github.com/SHCV-it/gnosis.git
cd gnosis
pip install -e . pytest python-frontmatter

# Run tests (offline — only localhost fixtures)
python -m pytest tests/ -q -v
```

### Project structure

```
gnosis/
  cli/           Click CLI (single page, crawl, dry-run, manifest)
  config/        YAML loading + typed settings dataclass
  core/
    downloader   Async HTTP client, auth, retries, FetchResult
    converter    HTML → Markdown, boilerplate stripping, metadata extraction
    crawler      BFS crawler with concurrent batch fetching
    provenance   Frontmatter generation, content_hash, render_document
  integrations/  QMD pipeline (optional, heavy deps)
```

The test suite covers converter quality (comment/anchor/boilerplate/table
handling, shadow-table dedup, metadata), provenance generation (fields,
round-trip parsing, extras merging), auth header injection (3 schemes),
crawler link resolution, and CLI end-to-end behavior. Runs entirely offline.

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd
like to change.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Run the tests (`python -m pytest tests/ -q`)
4. Commit your changes with clear messages
5. Push and open a pull request against `main`

## Related projects

Gnosis is designed to feed documentation pipelines and LLM knowledge bases.
Pair it with:

- **n8n / cron / Airflow** — schedule gnosis runs and pipe results into your
  downstream pipeline
- **QMD** — local vector search via the `--qmd-index` flag
- **Any Markdown-to-anything pipeline** — the YAML frontmatter is parseable by
  python-frontmatter, Jekyll, Hugo, Obsidian, and standard static-site generators

## License

MIT — see [LICENSE](LICENSE).

---

**Author:** Steffen Hoehne, [SHCV.IT](https://shcv.it)
