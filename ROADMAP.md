# Gnosis — Roadmap to "Best-in-Class"

> The north star: **the best open-source project for getting data from the internet into a knowledge-base/LLM-ready format — with verifiable, byte-level provenance.**

## Thesis (settled by a 10-persona adversarial panel)

Everyone in this space (Firecrawl, Crawl4AI, Jina Reader) competes on *cleanliness, scale, and agents*. **Nobody owns verifiability.** Gnosis wins the uncontested moat:

> **Markdown is a projection; the raw bytes + WARC are the source of truth.**

Positioning: *"The auditable one"* — byte-level SHA-256, WARC archival, replayable, re-fetchable, self-describing provenance on every artifact.

## Architecture spine

One canonical record flows through every stage; every heavy capability is an optional plugin behind a narrow seam.

```
CaptureRecord {
  raw_bytes,  bytes_sha256,        # wire truth (hash the BYTES, not the markdown)
  content_sha256,                  # hash of derived Markdown (secondary)
  content_type, final_url, requested_url, redirect_chain,
  status_code, response_headers, fetched_at,
  engine, version, render_mode, render_timestamp, js_executed
}

capture ─▶ extract ─▶ provenance ─▶ archive ─▶ emit
 (fetch)    (bytes→MD)  (frontmatter)  (WARC+store)  (md/json/chunks/llms.txt)
     └─ static httpx (default) ─┘
     └─ browser backend (optional extra) ─┘
```

**Runtime boundary:** pure-Python MIT core (`httpx`, `bs4`/`lxml`, `pyyaml`, `click`, `rich`). Browser (Obscura/Playwright), documents (MarkItDown/Docling), and LLM extraction are **optional extras — never statically linked**.

**Non-negotiable security gates:** SSRF/private-network validation per redirect hop; secrets via `${ENV_VAR}` only and never into the browser process; pinned + hashed binaries.

## "Absolutely steal" (source-tagged)

| Capability | Source |
|---|---|
| YAML provenance frontmatter (`url`, `fetched_at`, `status_code`, `etag`, `last_modified`, `requested_url`, `generator`) | gnosis |
| **Byte-level SHA-256 over raw wire bytes** + `raw_bytes` in fetch record | gap (fix) |
| WARC archival + replay; content-addressed store (sha256 = path) | warcio/pywb, Common Crawl |
| Static async fetch + redirects + retries/backoff + rate-limit (default rung) | gnosis |
| robots.txt + AutoThrottle **enforced** (fix the dead `respect_robots` flag) | scrapy |
| Optional JS render backend behind one seam, static-first + auto-escalate | obscura/crawl4ai/firecrawl |
| Main-content detection + class-word boilerplate strip; valid GFM tables | gnosis/trafilatura |
| Chunking + numbered citations (output mode) | crawl4ai |
| `llms.txt`/`llms-full.txt` + sitemap ingestion | standard |
| Plugin converter architecture (heavy deps as extras) | markitdown |
| CLI + exit codes + YAML config + JSON manifest | gnosis |
| One-command demo + reproducible benchmark (`gnosis bench`) | gap |

## What we deliberately skip

- Agentic autonomous browsing (browser-use) — non-deterministic, un-auditable.
- Native V8/PyO3 embed — license + build + CVE blast radius (revisit only if a prebuilt wheel appears).
- LLM structured extraction / BM25 / image captioning in core — plugin-only.
- Distributed queue/webhooks/cluster in v1 — v2.
- Screenshot/PDF/MCP as core — post-proof plugins.

## Issue checklist

| # | Issue | Phase |
|---|---|---|
| 1 | CI pipeline: test + lint + build | Foundation |
| 2 | Modernize packaging (single-source pyproject, fix `name` mismatch, ruff) | Foundation |
| 3 | Provenance fix: byte-level hash + `raw_bytes`/`redirect_chain` capture | v1 moat |
| 4 | Enforce robots.txt + politeness (wire up `respect_robots`) | v1 moat |
| 5 | SSRF/private-network guard on fetch + redirects | v1 security |
| 6 | WARC export + content-addressed store | v1 moat |
| 7 | Optional render backend (`Renderer` protocol + adapter), static-first | v1 |
| 8 | `gnosis bench` reproducible benchmark + scorecard | v1 proof |
| 9 | Chunking + numbered citations output mode | v2 |
| 10 | `llms.txt`/`llms-full.txt` emission + sitemap ingestion | v2 |
| 11 | Checkpoint/resume crawl keyed on `content_hash` | v2 |
| 12 | Document converters as optional plugins (MarkItDown/Docling) | v2 |
| 13 | README overhaul: SEO-optimized, attractive, positioning + comparison | polish |
| 14 | PyPI polish: metadata, keywords, classifiers, URLs, license/NOTICE | polish |
| 15 | Full-sweep deep test + security + performance audit | final gate |

## Execution protocol (per issue)

1. Branch `feat/issue-N-<slug>` from `main`.
2. Implement + add/update tests.
3. Run the full suite locally (`pytest`) until green — E2E for CLI-facing changes.
4. Push branch, open a PR.
5. Deploy an **independent QA subagent** to review the diff against the issue's acceptance criteria.
6. Merge only after QA passes; re-run CI.

**Final gates:** full-sweep deep testing (offline + live fixtures, all platforms), a 10-persona panel audit of *ease-of-use, understandability, SEO, and README attractiveness*.
