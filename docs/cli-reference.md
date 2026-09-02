# CLI Reference

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

## Configuration

Copy `gnosis/config/default.yaml` and pass it with `-c`. Sections:

- `downloader` — timeout, retries, user agent, rate limit, robots, SSRF, headers, auth
- `crawler` — max depth, max pages, concurrency
- `converter` — excluded tags, content selectors, boilerplate stripping
- `output` — directory, overwrite, frontmatter, WARC, chunk
- `render` — enabled, auto, engine, timeout
