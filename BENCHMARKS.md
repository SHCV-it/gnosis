# Benchmarks

> Reproducible evidence for the claims in the [README](README.md). Every
> number below was produced by `gnosis-bench` against live sites — re-run it
> yourself to verify.

## Run it

```bash
pip install gnosis-markdown
printf '%s\n' \
  'https://example.com/' \
  'https://www.python.org/' \
  'https://en.wikipedia.org/wiki/Markdown' \
  'https://httpbin.org/html' \
  'https://news.ycombinator.com/' \
  'https://www.gnu.org/' \
  'https://www.rfc-editor.org/rfc/rfc3986' \
  > urls.txt
gnosis-bench --urls urls.txt -o bench-report.json
```

The JSON report is machine-readable and records, per URL: HTTP status, latency,
raw byte count, markdown character count, and whether **provenance is complete**
(`bytes_sha256` + `content_hash` + WARC record present).

## Latest scorecard (v2.4.2, 2026-09-07)

| Metric | Value |
|---|---|
| Corpus size | 7 |
| Successful | 7/7 |
| Success rate | 100.0% |
| Avg latency | 2101 ms |
| Avg markdown/raw ratio | 0.363 |
| **Provenance complete** | **7/7** |
| Token estimate | 55,486 |

### Per-URL

| URL | Status | Latency | Raw bytes | Markdown chars | Provenance |
|---|---|---|---|---|---|
| https://example.com/ | 200 | 963 ms | 559 | 168 | ✅ |
| https://www.python.org/ | 200 | 700 ms | 52,851 | 4,929 | ✅ |
| https://en.wikipedia.org/wiki/Markdown | 200 | 1339 ms | 311,719 | 43,326 | ✅ |
| https://httpbin.org/html | 200 | 2742 ms | 3,741 | 3,598 | ✅ |
| https://news.ycombinator.com/ | 200 | 2403 ms | 34,430 | 18,649 | ✅ |
| https://www.gnu.org/ | 200 | 3225 ms | 31,659 | 8,868 | ✅ |
| https://www.rfc-editor.org/rfc/rfc3986 | 200 | 3335 ms | 636,877 | 142,406 | ✅ |

## What "provenance complete" means

For every successful fetch gnosis writes, in the frontmatter of the output
Markdown:

- `bytes_sha256` — SHA-256 of the **response body bytes** (after content decoding; not derived markdown)
- `content_hash` — SHA-256 of the markdown body
- `fetched_at`, `status_code`, `url`, `generator`
- optional `retention_ratio`, `stripped_elements`, `low_content`

and, when archival is enabled, a WARC `response` record keyed by `bytes_sha256`
in the content-addressed store. This is the moat: the raw bytes are the source
of truth, and every output can be traced back to them.
