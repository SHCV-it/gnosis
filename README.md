# Gnosis

**Website → clean, provenance-stamped Markdown.** Point gnosis at a URL and get
LLM-friendly markdown files with a YAML frontmatter block recording exactly
where the content came from, when it was fetched, and how to verify it.

Built for feeding knowledge bases, documentation pipelines, and LLM context
stores — where "which page did this come from, and has it changed?" is a
question you should never have to answer by hand.

## Features

- **Single page or full site** — one URL, or crawl every page under a path with `--all`
- **Provenance frontmatter by default** — every file records source URL, fetch
  timestamp (UTC), SHA-256 content hash, HTTP status, page metadata
  (title/author/language), and ETag/Last-Modified when the server provides them
- **Authentication built in** — Bearer tokens, HTTP Basic (works with
  Confluence Cloud API tokens), or arbitrary headers. Secrets always come from
  environment variables, never from the command line or config files
- **Clean extraction** — main-content detection with precedence-ordered
  selectors, boilerplate stripping (sidebars, breadcrumbs, cookie banners,
  permalinks), and framework-aware fixes for Confluence, ReadTheDocs/Sphinx,
  and GitHub-style pages
- **Tables that survive** — GFM-compatible output: multi-paragraph cells joined
  with `<br>`, pipes escaped, sticky-header clone tables deduplicated
- **Politeness** — configurable per-request delay, retries with exponential
  backoff, robots-aware design
- **Scheduler-friendly** — headless CLI, meaningful exit codes, JSON crawl
  manifest; drops straight into cron, n8n, Airflow, or a CI job
- **Optional QMD integration** — index output into a QMD knowledge base with
  local-LLM context generation (`pip install gnosis[qmd]`)

## Installation

```bash
git clone https://github.com/SHCV-it/gnosis.git
cd gnosis
python -m venv venv && source venv/bin/activate
pip install -e .
```

Optional, only if you use `--qmd-index` (pulls torch + transformers):

```bash
pip install -e .[qmd]
```

Requires Python 3.12+.

## Quick start

```bash
# One page
gnosis https://docs.python.org/3/tutorial/

# Whole section of a docs site
gnosis https://docs.python.org/3/tutorial/ --all -o ./python-docs/

# Preview scope without downloading
gnosis https://docs.python.org/3/tutorial/ --all --dry-run
```

Output for `https://trafilatura.readthedocs.io/en/latest/quickstart.html`:

```markdown
---
title: Quickstart — Trafilatura 2.2.0 documentation
url: https://trafilatura.readthedocs.io/en/latest/quickstart.html
fetched_at: '2026-08-04T10:24:17Z'
content_hash: 1549512c3f441ce691fac68a9fcdcb87497cb187a71afe2503bb13465ea716fd
status_code: 200
generator: gnosis/1.1.0
language: en
etag: '"61e917f4cd107c3bce6182b633819fcf"'
last_modified: Fri, 31 Jul 2026 16:07:37 GMT
---

# Quickstart

Trafilatura is a tool that simplifies the process of turning raw HTML into
structured, meaningful data. ...
```

## Provenance: the contract

Every file gnosis writes is self-describing. Default frontmatter fields:

| Field | Meaning |
|---|---|
| `title` | Page title (`og:title` preferred, entities unescaped) |
| `url` | Final URL after redirects (`requested_url` added if different) |
| `fetched_at` | UTC fetch timestamp, ISO 8601 |
| `content_hash` | SHA-256 of the markdown body — dedup/change detection |
| `status_code` | HTTP status of the final response |
| `language` | `<html lang>` or `og:locale`, when present |
| `author`, `description`, `site_name` | From meta/OG tags, when present |
| `published_time`, `modified_time` | From `article:*` tags, when present |
| `etag`, `last_modified` | Response caching headers, when sent |
| `generator` | gnosis version that produced the file |

Add your own constant fields (tags, owners, downstream routing hints) per run
or per config — they merge in without ever overriding the core fields:

```bash
gnosis https://example.com/docs --frontmatter 'tags: [customs, passar]' --frontmatter 'owner: kb-team'
```

The frontmatter is standard YAML between `---` fences: parseable by
python-frontmatter, Jekyll, Hugo, Obsidian, and any downstream pipeline.

## Authenticated fetching (Confluence Cloud & co.)

Secrets are read from **environment variables only** — never CLI arguments
(they leak into shell history) and never committed config files.

### Confluence Cloud with a Personal Access Token

Confluence Cloud API tokens use HTTP Basic with `email:api-token`:

```bash
export CONFLUENCE_PAT="your-api-token"
gnosis "https://your-domain.atlassian.net/wiki/spaces/SPACE/pages/123456789/Page+Title" \
  --basic-user you@example.com \
  --basic-token-env CONFLUENCE_PAT
```

### Bearer token

```bash
export MY_API_TOKEN="..."
gnosis https://internal.example.com/docs --bearer-token-env MY_API_TOKEN
```

### Arbitrary headers

```bash
gnosis https://example.com --header "X-Api-Key: ${MY_KEY}" --header "X-Team: docs"
```

### Via config file

```yaml
downloader:
  auth:
    type: basic                      # bearer | basic | header
    username: "you@example.com"
    password: "${CONFLUENCE_PAT}"    # ${ENV_VAR} expanded at load time
```

## How clean is the output?

Gnosis is opinionated about boilerplate. By default it:

- strips `script/style/nav/footer/aside/form/template/...` tags and HTML
  comments (including SSR markers like Confluence's `data-loadable` comments)
- removes elements matching exact `strip_classes` tokens **and** boilerplate
  *words* (`sidebar`, `toc`, `breadcrumb`, `cookie`, …) inside namespaced class
  names — so `bd-sidebar-primary` goes, but `research-content` stays
- removes permalink anchors inside headings (`# Quickstart#` → `# Quickstart`)
- picks the main content area by precedence-ordered selectors
  (`.markdown-body`, `.ak-renderer-document`, `.wiki-content`, … before
  `main`/`#content`), so platform chrome never leaks into content
- converts tables to valid GFM: multi-line cells joined with `<br>`, `|`
  escaped, duplicate/sticky-header rows removed
- resolves relative links to absolute URLs; skips `data:`-URI images
  (spacers/tracking pixels)

Everything above is configurable — see [`config/default.yaml`](config/default.yaml).

## CLI reference

```
gnosis URL [OPTIONS]

  -a, --all                     Crawl all child pages under the URL path
  -n, --dry-run                 Discover and count pages only (requires --all)
  -o, --output DIR              Output directory
  -c, --config FILE             YAML configuration file
  -f, --overwrite               Overwrite existing files
  -q, --quiet                   Suppress progress output
  -v, --verbose                 Show detailed conversion diagnostics
      --no-frontmatter          Write bare markdown without provenance block
      --frontmatter KEY: VALUE  Extra constant frontmatter field (repeatable)
      --header NAME: VALUE      Extra request header, ${ENV_VAR} expanded (repeatable)
      --bearer-token-env VAR    Bearer token from environment variable
      --basic-user USER         HTTP Basic username (with --basic-token-env)
      --basic-token-env VAR     HTTP Basic password/token from environment variable
      --qmd-index               Index output into QMD (requires [qmd] extra)
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (crawl mode: at least one page saved) |
| `1` | Failure — download error, file exists without `-f`, nothing saved, bad flags |
| `130` | Interrupted (Ctrl-C) |

In `--all` mode a `_manifest.json` is written to the output directory listing
every page with its URL, file, content hash, fetch timestamp, and status —
suitable for schedulers and downstream bookkeeping.

## Configuration

All defaults live in [`config/default.yaml`](config/default.yaml) — copy it and
pass with `-c`. Highlights:

```yaml
downloader:
  timeout: 30
  retries: 3
  rate_limit_ms: 500          # politeness delay between requests
  headers: {}                 # extra headers, ${ENV_VAR} expanded
  auth:                       # bearer | basic | header
    type: bearer
    token: "${MY_API_TOKEN}"

crawler:
  max_depth: 10
  max_pages: 500

converter:
  content_selectors: [...]    # tried in order, first substantial match wins
  strip_classes: [...]        # exact class-token matches
  strip_class_words: [...]    # word-level matches inside class names

output:
  frontmatter: true           # provenance block on every file
  frontmatter_extra: {}       # constant fields added to every file
```

## Development

```bash
pip install -e . pytest python-frontmatter
python -m pytest tests/ -q
```

The test suite covers converter quality (comment/anchor/boilerplate stripping,
table handling, shadow-table dedup), provenance generation, auth header
handling against a local echo server, crawler link resolution, and CLI
end-to-end behavior — all offline except localhost.

## License

MIT License — see [LICENSE](LICENSE).

## Author

Steffen Hoehne, [SHCV.IT](https://shcv.it)
