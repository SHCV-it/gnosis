# gnosis-markdown

> **The citation layer for LLM pipelines.** Fetch a page, crawl a site, and get
> clean, LLM/RAG-ready Markdown — with the evidence attached to prove where
> every byte came from.

gnosis-markdown is an open-source Python CLI and library (MIT) that converts web
pages and documents into clean Markdown for RAG pipelines, knowledge bases, and
fine-tuning datasets. The Markdown is the part you read; the **Capture Record**
is the part that makes it trustworthy.

> **Markdown is a projection; the raw bytes + WARC are the source of truth.**

Every file gnosis-markdown writes carries a machine-readable statement of where
its bytes came from, when they were fetched, and how to verify them against the
original response — down to the byte. No sidecar bookkeeping, no "trust us."

Built for **RAG engineers** who need citation-anchored chunks, **compliance and
data teams** who must evidence what they ingested, and **security-sensitive
researchers** who need to prove a document's origin.

[PyPI](https://pypi.org/project/gnosis-markdown/) ·
[Source](https://github.com/SHCV-it/gnosis) ·
[DOI 10.5281/zenodo.22276101](https://doi.org/10.5281/zenodo.22276101) ·
MIT · Python 3.12+ · maintained by [SHCV.IT](https://shcv.it)

---

## Why gnosis-markdown

Most web-to-Markdown tools are judged on extraction speed. gnosis-markdown is
judged on **auditability**. It does not compete to be the fastest scraper — it
is the layer that makes whatever you scrape *provable*.

When a model answers, an auditor asks, and a pipeline is challenged, the
question is always the same: **where did this come from?** gnosis-markdown is
the answer.

## The moat: the Capture Record Specification

The value of gnosis-markdown is not the scraper — it's the **contract**. The
[Capture Record Specification](capture-record-spec.md) is an open, MIT-licensed,
machine-readable format for stating what was fetched, from where, when, and how
to verify the stored copy against the original response.

It separates two claims that the rest of the field conflates:

- **Custody** — what was fetched, from where, when, and is the stored copy
  unaltered? *Solved:* hash the bytes.
- **Fidelity** — how much of the source actually survived extraction?
  *Measured:* `retention_ratio`, `stripped_elements`, `low_content`.

That openness is the moat — the format is the product.

## Features

### Provenance & audit

- **`bytes_sha256`** — SHA-256 of the response body bytes, after content
  decoding. The *audit* hash.
- **`content_hash`** — SHA-256 of the derived Markdown, for dedup and change
  detection. Two hashes, two jobs.
- **WARC archival** (`--warc`) — ISO 28500 replayable archives plus a
  content-addressed store keyed on `bytes_sha256`.
- **Ed25519 signing** (`--sign`) — a seal of origin; `gnosis-keygen` and
  `gnosis-verify` generate and check keys with pinned-key verification.
- **Data cards** — every job writes a `data-card.json` summarising what was
  captured and how.

### Consent, policy, and compliance

- **ai.txt / llms.txt consent recording** — recorded in the Capture Record.
  Advisory by default, deliberate by design.
- **Compliance policy engine** — ordered allow/deny rules with **deny
  overrides allow**, plus `--profile` presets (`strict-optout`, `open-only`).

### Security

- **IP-pinned SSRF guard** — resolves once, validates every address, dials the
  validated IP (closes the DNS-rebinding TOCTOU). Auth headers never leak to
  cross-origin redirects.

### Citations, export, integration

- **Token-aware chunking** (`--chunk`) with exact byte offsets and `chunk_sha256`.
- **`llms.txt` + `llms-full.txt`** emission on every crawl.
- **Multi-format export** — `--format json|jsonl|parquet`.
- **MCP server** (`gnosis-mcp`), **LlamaIndex reader**, **LangChain loader**,
  and **plugin hooks**.
- **Incremental crawl + conditional GET** and **resumable crawls**.

---

## Quick start

Requires **Python 3.12+**.

```bash
pip install gnosis-markdown

# One page → one Markdown file
gnosis https://docs.python.org/3/tutorial/

# Crawl an entire section
gnosis https://docs.python.org/3/tutorial/ --all -o ./python-docs/

# Archive the raw bytes + sign the record
gnosis https://docs.python.org/3/tutorial/ --warc --sign --sign-key key.pem

# Verify the provenance claim yourself
shasum -a 256 out/.gnosis-store/<bytes_sha256>   # matches the hash in the .md
```

The provenance claim is the product. **Verify it — don't trust it.**

## Start here

- [Getting Started](getting-started.md) — install and first command
- [Capture Record Specification](capture-record-spec.md) — the provenance contract
- [Provenance](provenance.md) — how to verify what you captured
- [CLI Reference](cli-reference.md) — every flag and entry point
- [Architecture](architecture.md) — how it's built
