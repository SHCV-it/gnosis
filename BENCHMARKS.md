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
  > urls.txt
gnosis-bench --urls urls.txt -o bench-report.json
```

The JSON report is machine-readable and records, per URL: HTTP status, latency,
raw byte count, markdown character count, and whether **provenance is complete**
(`bytes_sha256` + `content_hash` + WARC record present).

## Latest scorecard (v1.4.1, 2026-09-02)

| Metric | Value |
|---|---|
| Corpus size | 5 |
| Successful | 5/5 |
| Success rate | 100.0% |
| Avg latency | 1827 ms |
| Avg markdown/raw ratio | 0.405 |
| **Provenance complete** | **5/5** |
| Token estimate | 17,553 |

### Per-URL

| URL | Status | Latency | Raw bytes | Markdown chars | Provenance |
|---|---|---|---|---|---|
| example.com | 200 | 947 ms | 559 | 168 | ✅ |
| python.org | 200 | 1339 ms | 52,476 | 4,473 | ✅ |
| en.wikipedia.org/wiki/Markdown | 200 | 1228 ms | 311,719 | 43,326 | ✅ |
| httpbin.org/html | 200 | 3173 ms | 3,741 | 3,598 | ✅ |
| news.ycombinator.com | 200 | 2448 ms | 34,533 | 18,649 | ✅ |

## What "provenance complete" means

For every successful fetch gnosis writes, in the frontmatter of the output
Markdown:

- `bytes_sha256` — SHA-256 of the **raw response bytes** (not derived markdown)
- `content_hash` — SHA-256 of the markdown body
- `fetched_at`, `status_code`, `url`, `generator`
- optional `retention_ratio`, `stripped_elements`, `low_content`

and, when archival is enabled, a WARC `response` record keyed by `bytes_sha256`
in the content-addressed store. This is the moat: the raw bytes are the source
of truth, and every output can be traced back to them.
