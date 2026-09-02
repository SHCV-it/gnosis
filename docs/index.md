# Gnosis

**The auditable web scraper that turns the internet into LLM-ready knowledge.**

Gnosis downloads websites (and documents) and converts them into clean,
LLM-friendly Markdown — with a YAML provenance block on every file recording
where the bytes came from, when they were fetched, and how to verify them.

> **Markdown is a projection; the raw bytes + WARC are the source of truth.**

Unlike Firecrawl, Crawl4AI, or Jina Reader, gnosis ships **byte-level SHA-256**
and **WARC-grade evidence** out of the box.

## Why Gnosis

| Feature | Gnosis | Firecrawl | Crawl4AI | Jina Reader |
| --- | --- | --- | --- | --- |
| Clean Markdown | ✅ | ✅ | ✅ | ✅ |
| JS rendering | ✅ opt-in | ✅ | ✅ | ✅ |
| Byte-level SHA-256 provenance | ✅ | ❌ | ❌ | ❌ |
| WARC archival (replay via pywb) | ✅ | ❌ | ❌ | ❌ |
| Built-in SSRF guard | ✅ | ⚠️ | ❌ | ❌ |
| robots.txt + politeness | ✅ | ⚠️ | ⚠️ | ❌ |
| Self-hostable / offline | ✅ | ✅ | ✅ | ✅ |
| License | MIT | AGPL-3.0 | Apache-2.0 | MIT |

✅ yes · ⚠️ partial · ❌ no — *as of September 2026.*

## Start here

- [Getting Started](getting-started.md) — install and first command
- [Provenance](provenance.md) — the audit contract
- [CLI Reference](cli-reference.md) — every flag
- [Architecture](architecture.md) — how it's built
