# Changelog

## [Unreleased]

### Fixed
- **SSRF DNS-rebinding TOCTOU**: the guard previously resolved and validated a
  hostname, then let httpx resolve again independently at connect time. It now
  resolves once, validates *every* returned address, and pins the connection to
  a validated IP via a custom `httpcore` network backend (`PinnedNetworkBackend`)
  wired into the downloader and robots checker through `SSRFPinnedTransport`.
  TLS SNI/certificate verification still uses the original hostname, so pinning
  does not weaken TLS.

## [1.4.3] - 2026-09-02

### Fixed
- WARC now writes `warcinfo` + `request` records (was response-only) — #1
- sitemap XML hardened against entity expansion via `defusedxml` — #2
- token-aware chunking hard-enforces `max_tokens` on unbreakable blocks — #3
- rate limiter is per-host (hostname key); a slow host no longer stalls others — #4

## [1.4.2] - 2026-09-02

### Fixed
- content protection now finds content *first* and protects the actual content
  elements (by id), so class-based selectors (`.markdown-body`, GitHub/GitLab)
  are protected — the earlier `find_parent` matched tag names only
- `retention_ratio` clamped to `[0, 1]` (markup overhead could still push a
  table/block-heavy page above 1.0)
- `low_content` flag now covered by a test
- README relative links + demo GIF made absolute so PyPI renders them

### Added
- `BENCHMARKS.md` — reproducible `gnosis-bench` scorecard (5/5 provenance-complete)
- `.github/ISSUE_TEMPLATE` (bug/feature) + `PULL_REQUEST_TEMPLATE`
- docs: token-aware chunking, IP-pinned SSRF guard, capture-quality gate

## [1.4.1] - 2026-09-02

### Fixed
- rate limiter keyed on netloc (was keyed on full URL, never fired — killed politeness + robots Crawl-delay compliance)
- `retention_ratio` now text-vs-text (was markdown-chars/source-chars, could report >1.0 on gutted pages)
- boilerplate word-matching no longer strips elements inside the main content
- capture-quality gate: `low_content` flag in frontmatter

## [1.4.0] - 2026-09-02

### Added
- Token-aware chunking: `max_tokens` sizing (dependency-free heuristic), boundary-anchored overlap, `token_count` + `chunk_sha256` in the manifest

### Security
- IP-pinned transport closes the SSRF DNS-rebinding TOCTOU (resolve once, dial validated IPs; allow-list classifier closes CGNAT/6to4/Teredo/NAT64)

### Changed
- llm/qmd integrations importable + tested without heavy deps; per-host rate limiting

## [1.3.0] - 2026-09-02

### Added
- Extraction provenance: `retention_ratio` + `stripped_elements` in the frontmatter (the audit trail now covers the transform, not just the bytes)
- Capture-quality warning when a page yields <150 chars (bot-block/truncation signal)

### Changed
- Crawl archives to WARC after content dedup (no duplicate records on resume)
- Removed dead code (crawler skip_urls, unused protocols, unused param); get_running_loop

## [1.2.1] - 2026-09-02

### Fixed
- WARC file appends instead of truncating on re-crawl
- resume re-expands the crawl frontier (dedup skips re-save)
- honest wording: raw response-body bytes, not wire bytes

## [1.2.0] - 2026-09-02

### Added
- **Byte-level provenance**: `bytes_sha256` (SHA-256 of the raw response bytes) recorded alongside `content_hash` (SHA-256 of the derived markdown); frontmatter also records `content_type` and `redirect_chain` when present.
- CI pipeline (pytest on 3.12/3.13 + ruff lint + wheel/sdist build) and ruff configuration (E/F/I rules, `gnosis` marked first-party).
- **robots.txt respect + politeness**: `respect_robots` now actually enforced (per-origin robots.txt via `urllib.robotparser`, fail-open on errors), and `Crawl-delay` is folded into the request rate limiter.

### Changed
- Packaging consolidated to a single `pyproject.toml`; removed `setup.py` and `requirements*.txt`. Default config now ships inside the package at `gnosis/config/default.yaml` (no more top-level `config/` namespace).

### Fixed
- Dataclass defaults aligned with `default.yaml` (`max_pages` 500; added `select`/`textarea`/`template` to `excluded_tags`).

## [1.1.0] - 2026-08-04

### Added
- **Provenance frontmatter on every output file** (on by default, `--no-frontmatter`
  to opt out): `title`, `url`, `fetched_at` (UTC ISO 8601), `content_hash`
  (SHA-256 of body), `status_code`, `language`, `author`, `description`,
  `site_name`, `published_time`/`modified_time`, `etag`/`last_modified`,
  `generator`. Standard YAML, parseable by python-frontmatter/Jekyll/Hugo.
- **Authentication**: Bearer, HTTP Basic (Confluence Cloud PAT pattern:
  email + API token), and arbitrary header auth. Secrets are read from
  environment variables only — via `--bearer-token-env`,
  `--basic-user`/`--basic-token-env`, or `${ENV_VAR}` expansion in config files
  and `--header` values.
- **User frontmatter extras**: `--frontmatter 'key: value'` (repeatable) and
  `output.frontmatter_extra` in config; merged without overriding core fields.
- **Crawl manifest**: `--all` runs write `_manifest.json` with per-page URL,
  file, content hash, timestamp, status, and title.
- **Metadata extraction**: `HTMLToMarkdownConverter.extract_metadata()`
  (title with entity unescaping, author, language, OG fields).
- **Downloader `fetch_result()`**: returns `FetchResult` with final URL,
  status code, fetch timestamp, and response headers. The crawler now carries
  this provenance through crawl mode.
- **Boilerplate word stripping**: `converter.strip_class_words` — word-level
  class matching catches framework-namespaced boilerplate
  (`bd-sidebar-primary`) without false positives (`research-content`).
- **Content selector precedence**: `content_selectors` are now tried in order
  and the first substantial match wins (matching the documented behavior);
  platform containers (`.markdown-body`, `.ak-renderer-document`,
  `.wiki-content`) precede chrome-wrapping landmarks (`main`, `#content`).
- **Test suite**: 47 pytest tests covering converter quality, provenance,
  auth, crawler resolution, and CLI end-to-end behavior.

### Fixed
- HTML comments no longer leak into output as text (Confluence
  `<!-- data-loadable-* -->` SSR markers polluted converted pages).
- Heading permalink anchors no longer glue `#` onto heading text
  (`# Quickstart#` → `# Quickstart`).
- Table cells with multiple paragraphs no longer break markdown rows
  (joined with `<br>`); pipes in cell text are escaped.
- Duplicate table header rows (Confluence thead+tbody repetition) and
  single-row sticky-header clone tables are removed.
- Relative links below extensionless "directory" URLs now resolve correctly
  (`/en/latest` + `quickstart.html` no longer escapes the crawl scope) —
  this previously broke `--all` crawls of most docs sites.
- `data:`-URI images (spacers/tracking pixels) are skipped.

### Changed
- torch/transformers are no longer core dependencies; install the QMD
  integration via `pip install gnosis[qmd]` (or `requirements-qmd.txt`).
- Blank-line collapsing in output is stricter (max one blank line).
- Default User-Agent updated to `Gnosis/1.1`.

## [1.0.0] - 2026-03-27

Initial public release: single-page download, `--all` crawling, configurable
extraction, QMD integration.
