# Design — HTTP server / API mode: the buyer's verdict + llm/qmd test coverage

> Panel review: `api-buyer`. Author: design panel (API consumer / adoption persona).
> Status: recommendation — no server exists today; this is the "would I buy it, and
> what would make me walk" review, not the implementation review (see
> `design-api-server.md` for architecture, `design-server-api-mode.md` for SRE,
> `design-api-server-security.md` for security).

## 1. Verdict

**Yes — adopt a server mode. But only if the API sells the moat.**

The single sentence that decides this for me as a buyer: *I already have
Firecrawl, Crawl4AI, and Jina Reader for "HTML → clean Markdown."* They are all
fine at that. The only reason I would self-host and integrate **gnosis** instead
is verifiability — byte-level SHA-256, WARC, redirect chain, re-fetchable
artifacts, SSRF guard. If the API returns `{"markdown": "..."}` and drops the
provenance, there is **zero switching-cost argument** and I stay on the hosted
product. Every must-have below follows from that one sentence.

So the API is not "the CLI over HTTP." The API is **the provenance contract,
served over HTTP.** The CLI stays the file-based reference implementation; the
API is the machine-readable expression of the same contract, and the two must
produce **byte-identical hashes** for the same input or the CLI is a lying
reference for what the API returns.

---

## 2. The buyer's litmus test

When I evaluate this, I ask four questions, in order:

1. **Can I get the raw-truth + hash + provenance in the same response as the
   markdown, without a second call?** If no → walk.
2. **Can I tell *programmatically* why a request failed, and retry only the
   retryable cases?** If errors are free-text HTTP bodies → walk.
3. **Is the optional stuff (qmd/llm/render) optional enough that the core
   server runs without a multi-GB torch install?** If `[server]` pulls torch →
   walk.
4. **Does a crawl come back as one deliverable (manifest + files + llms.txt +
   chunks + WARC), not as a pile I have to reassemble?** If I have to write the
   bookkeeping myself → walk.

Everything in §3–§7 is the concrete answer to those four questions.

---

## 3. What the API must have (non-negotiables)

### 3.1 Provenance is first-class in every response

`POST /v1/scrape` returns **one** JSON object that is a superset of the YAML
frontmatter, not a thin wrapper around it:

```json
{
  "requested_url": "https://docs.example.com/page",
  "final_url": "https://docs.example.com/page",
  "status_code": 200,
  "fetched_at": "2026-09-02T08:41:44Z",
  "redirect_chain": ["https://docs.example.com/page"],
  "content_type": "text/html; charset=utf-8",
  "etag": "\"61e917f4…\"",
  "last_modified": "Fri, 31 Jul 2026 16:07:37 GMT",
  "markdown": "# Title\n\n…",
  "content_hash": "<sha256 of markdown>",
  "bytes_sha256": "<sha256 of raw response bytes>",
  "chunks": [
    {"chunk_id":"c0","heading_path":["Title"],"start":0,"end":812,"char_count":812}
  ],
  "warc": {"path": ".gnosis-store/archive.warc.gz", "record_id": "…"}
}
```

`bytes_sha256` is the field I actually key on. It is the product. If I'm doing
RAG with citations, `chunks[].start/end` lets me anchor back to the exact span
(`markdown[start:end]`). Both must be in the same payload.

### 3.2 One round trip for one page

`/v1/scrape` is synchronous and returns the full object above. No
"POST then poll then download" for a single page — that pattern is fine for a
crawl job, it is hostile for a single URL.

### 3.3 Machine-readable errors — always `error.code`

A buyer builds a retry/alert policy off a stable enum, not off `str(response.text)`.
Every non-2xx body is:

```json
{"error": {"code": "upstream_timeout", "retryable": true, "message": "…", "request_id": "…"}}
```

The enum I require (stable, documented, versioned with the path):

| `code` | HTTP | retryable | meaning |
| --- | --- | --- | --- |
| `invalid_request` | 400 | no | bad JSON / missing `url` / bad URL / value above server cap |
| `auth_required` | 401 | no | missing or wrong API token |
| `robots_disallowed` | 403 | no | robots.txt disallows the URL |
| `private_network_blocked` | 403 | no | SSRF guard fired (generic body, no internal IP) |
| `rate_limited` | 429 | yes | inbound per-client limit; `Retry-After` set |
| `concurrency_limit` | 429 | yes | global semaphore exhausted; `Retry-After` set |
| `payload_too_large` | 413 | no | response body exceeded `max_response_bytes` |
| `upstream_error` | 502 | yes | target returned 5xx after retries |
| `upstream_timeout` | 504 | yes | target exceeded per-fetch/time budget |
| `not_implemented` | 501 | no | `qmd`/`render` requested but extra not installed |

`private_network_blocked` and `robots_disallowed` being *distinct* codes (not
one blob "forbidden") is important: one is "my URL is fine, retry elsewhere,"
the other is "never retry this URL." The API must not collapse them.

### 3.4 Versioned path + OpenAPI schema

`/v1/` prefix on every route, from day one. And an OpenAPI/JSON Schema document
is a **buyer requirement**, not a nice-to-have: it is how I generate a typed
client, how I diff contract changes, and how I argue "yes this is safe to call
from my pipeline." This is the one place I push back on the architect's
"Starlette, not FastAPI" note (`design-api-server.md` §2): the framework is
invisible to me, the **schema is not**. If Starlette, the team must hand-maintain
the schema and it *will* drift; FastAPI emits it for free. I'm fine with either
framework — but the schema must be generated from the same source of truth as the
route handlers, not written by hand.

### 3.5 A `batch` endpoint for N unrelated URLs

`/v1/scrape` is for one URL; `/v1/crawl` is for one URL's subtree. Neither serves
the case "I have 40 URLs from 40 different domains; give me 40 documents." I will
not make 40 round trips (latency × politeness throttle = terrible), and I will not
abuse `/crawl` for it. I need:

```
POST /v1/batch   {"urls": ["https://a.example", "https://b.example", …], "chunk": true}
```

Returns a single response: per-URL results + per-URL errors + a summary, with the
same `error.code`/provenance per item. Cap `len(urls)` server-side. This is the
endpoint that turns the API from "a scraper" into "a knowledge-base ingest tool."

### 3.6 A crawl comes back as one deliverable

`/v1/crawl` (or `/v1/jobs/{id}/result`) must return **the artifact bundle**, not
just page events. As a buyer I want, for one job id, one tarball or one directory
tree containing: `*.md`, `*.md.chunks.json`, `_manifest.json`, `llms.txt`,
`llms-full.txt`, and the WARC + `.gnosis-store`. Streaming NDJSON progress is a
nice-to-have for long jobs; the *bundle* is the deliverable. I am not going to
reconstruct `llms.txt` from a stream of page events myself.

### 3.7 Deterministic + idempotent

The content-addressed store means "same bytes → same `bytes_sha256` → same
artifact." I want that exposed, not buried: if I re-submit the same URL, I should
get either (a) a cache hit with the previous `bytes_sha256`/`content_hash`, or (b)
a fresh fetch with a *detectable* change in hash. That is the entire point of
"auditable." A `crawl` job should also be idempotent-keyable so a retried client
doesn't double-crawl.

### 3.8 CLI and API produce byte-identical output

`gnosis https://x --chunk` and `POST /v1/scrape {"url":"https://x","chunk":true}`
must yield the same `content_hash`, `bytes_sha256`, and chunk offsets. The moment
the two front-ends diverge, the CLI stops being a trustworthy reference and the
provenance claim ("re-fetch and re-verify") breaks for API users. This is the
sharpest argument for the **one service layer, two front-ends** refactor that both
the SRE and architect docs already propose (`gnosis/service.py` returning typed
`PageResult`/`CrawlResult`). I don't care about the code, I care about the
invariant it enforces.

---

## 4. The surface I'd actually buy

Minimal, but one route more than the architect's five, and provenance-first:

| Method + path | Returns |
| --- | --- |
| `GET /healthz` | `200 {"status":"ok","version":…}` (no auth, no info leak) |
| `GET /readyz` | `200 {"ready":true,"qmd_available":false}` / `503` |
| `POST /v1/scrape` | full `ScrapeResult` (3.1) |
| `POST /v1/batch` | `{results:[ScrapeResult…], errors:[{url,error}…], summary:{…}}` |
| `POST /v1/crawl` | `202 {job_id}` (or streaming NDJSON if `Accept: application/x-ndjson`) |
| `GET /v1/jobs/{id}` | `{status, pages_done, pages_failed, error}` |
| `GET /v1/jobs/{id}/result` | result bundle (tarball or file listing) |
| `POST /v1/index/qmd` | `501 not_implemented` when extra absent; else `200 {collection, context_description, embedded}` |
| `GET /openapi.json` | the schema (3.4) |

---

## 5. Dealbreakers (I walk if any of these is true)

1. **`allow_private_network` is settable per-request.** Then the API is an
   internal-network scanner I must not expose. SSRF guard stays on and is
   operator-config only, never a request field. (All three prior docs agree; I'm
   just recording it as my hard exit.)
2. **`[server]` pulls `torch`/`transformers`.** The core + server install must
   stay lean. Heavy deps live in `[qmd]`/`[docs]`, behind lazy imports.
3. **Errors are HTTP status + free text.** No `error.code` → no robust retry
   policy → I hand-roll string matching → I walk.
4. **No `/v1/` and no OpenAPI schema.** Contract churn is a maintenance tax I
   refuse to pay.
5. **Crawl results aren't retrievable as a bundle.** I won't reassemble
   `llms.txt`/manifest/WARC from events.
6. **`/index/qmd` failure can take down `/scrape`.** The optional path must never
   be able to crash the core (a hung `qmd embed` subprocess, a torch OOM, or a
   missing model must degrade to `501`/skip — never `500` the whole worker).

---

## 6. The optional llm/qmd integrations: the buyer's trust contract

The core server is only as trustworthy as its *optional* seams. My contract:

> **`pip install gnosis-markdown[server]` runs `/v1/scrape` and `/v1/crawl` with
> no torch on the machine, no `qmd` binary, and no model download. Every optional
> capability degrades to a distinct, documented `error.code` without affecting the
> core.**

Three concrete defects stand in the way of that contract today, in order of
buyer-pain:

1. **`integrations/llm.py` imports `torch` and `transformers` at module top.**
   This means the module cannot even be *imported* without `[qmd]`, so any server
   code that imports it at startup (to register `/v1/index/qmd`) drags torch into
   the core process. Fix by moving the heavy imports into `_load_model()` —
   exactly the lazy-import pattern `integrations/documents.py` already uses for
   MarkItDown, and `cli/main.py::run_qmd_integration` already uses for
   `LLMContextGenerator`. This is the single highest-value testability fix.

2. **The LLM prompt is polluted with provenance frontmatter.** `_aggregate_content`
   reads the raw `.md` including the YAML frontmatter (`bytes_sha256`, `etag`,
   `redirect_chain`, …). That is wasted context-window and *noise* for the
   one-sentence-description task. Reuse the existing `_read_md_body` helper (in
   `cli/main.py`) to strip it before aggregation. The api-sec doc flagged this
   too; I care because it degrades the *quality* of the output I'm paying tokens for.

3. **`_generate` hardcodes `do_sample=True`.** A buyer wants reproducibility:
   `temperature=0` should force greedy decoding, not still sample. Deterministic
   context descriptions are a feature; silent randomness is a bug.

The SRE doc's four async-concurrency bugs (global per-process rate limiter,
blocking subprocess/torch on the loop, non-concurrency-safe WARC writer, no job
drain) are real and I second them from the consumer side: each one becomes "the
API is slow/inexplicably broken under my load" the day I integrate. They are
table-stakes, not polish.

---

## 7. Test coverage I require (specific + hermetic)

I don't measure coverage in "%"; I measure it in **behaviors pinned**. The named
gap is real: there is no `tests/test_qmd.py`, no `tests/test_integrations_llm.py`,
and the existing optional-dep test (`tests/test_documents.py`) is an anti-pattern —
it `skipif`s exactly when `markitdown` **is** installed, so the positive path
never runs in any CI leg and the negative path never runs in the `[docs]` leg.
Fix the pattern, then test both directions.

**Hard rules:**

- **No torch in default CI.** Test `llm.py` with `torch`/`transformers` stubbed at
  the module-import boundary (or injected fake model/tokenizer), never by
  downloading a model. A real-model smoke test is `@pytest.mark.skipif(not
  os.getenv("GNOSIS_LLM_SMOKE"))`, off by default.
- **No `qmd` binary in CI.** Test `qmd.py` by monkeypatching `shutil.which` and
  `subprocess.run`; assert argv construction and the `"already exists"` retry
  branch; assert a hostile `collection_name` (`http://evil.com/$(id)`) is passed
  as a list argv element, never interpreted by a shell.

**The specific behaviors I require covered:**

`test_integrations_llm.py` (stubbed model, no weights):
- module **imports** with torch/transformers absent (regression guard for the
  6.1 fix — currently this test would fail, which is the point).
- `_aggregate_content`: `sample_files_limit` cap; `sample_content_max_chars`
  truncation + `[... truncated ...]`; single-file header stripped; unreadable file
  skipped; empty → `"No content available."`; `> max_files` note appended;
  **frontmatter stripped** (6.2 fix).
- `_clean_thinking_tags`: multiline `<think>…</think>` stripped, blank lines
  collapsed.
- `/no_think` appended **only** when `"qwen"` in model name.
- `generate_context`: with fake model/tokenizer, returns stripped description;
  `_load_model` failure → `RuntimeError("Failed to load LLM model: …")`.
- `temperature=0` → greedy (`do_sample=False`) path (6.3 fix).

`test_qmd_integration.py` (mocked subprocess, no binary):
- `_verify_qmd_installed` → `QMDNotFoundError` when `shutil.which("qmd") is None`.
- `_run_command` nonzero exit → `QMDCommandError` with exit code + stderr in
  message; **`timeout=`** present on the `subprocess.run` call.
- `add_collection` exact argv; `"already exists"` → parse name → remove → retry;
  retry-fails → `QMDCommandError`.
- `_parse_existing_collection_name` against real QMD output fixtures.
- `run_pipeline` call order: add_collection → add_context → embed.
- `embed(force=True)` appends `-f`.

Wiring (`run_qmd_integration` / server route):
- `settings.qmd.enabled == False` → no-op, core output intact.
- `QMDIntegrator()` raising `QMDNotFoundError` → graceful skip, scrape output
  preserved, exit 0.
- `LLMContextGenerator.generate_context` raising → graceful skip, scrape output
  preserved, exit 0.
- full success → `run_pipeline` invoked with the right collection name + context.

Server route:
- `POST /v1/index/qmd` → `501 not_implemented` when extra absent (with the
  `error.code`, per §3.3).
- `GET /openapi.json` → schema present and valid (the 3.4 requirement is a test,
  not a wish).

CI legs: default offline stub tests; a gated `qmd-integration` leg (real `[qmd]`
install + tiny model + `qmd` binary) that is *not* on every push. The point is
that the default suite is fast, offline, and proves the degradation contract.

---

## 8. Willing to defer (v2)

- Webhooks/callbacks — polling `/v1/jobs/{id}` is acceptable for v1; a callback
  is the thing that would make it a *hosted-style* product, but it's v2.
- Multi-tenant API keys / scoped tokens / billing — one shared bearer key
  (`GNOSIS_API_TOKEN`, `hmac.compare_digest`) is the v1 minimum; scoped tokens
  (scrape vs crawl vs admin) are strongly wanted but v1.1.
- Redis-backed queues and scale-out — single-process uvicorn with a global
  semaphore covers "self-hosted single operator" which is the actual buyer today.
- The `batch` endpoint could ship as v1.0 or v1.1; it's the one thing on my list
  I'd accept landing second, as long as it lands before I have to build a
  40-URL ingest loop.

---

## 9. Acceptance criteria (for the eventual issue)

1. `POST /v1/scrape` returns `bytes_sha256`, `content_hash`, `redirect_chain`,
   `chunks[]`, and `markdown` in one response; CLI and API produce identical
   hashes for the same URL.
2. Every error body carries a stable `error.code` from §3.3; `robots_disallowed`
   and `private_network_blocked` are distinct codes.
3. `/v1/` prefix + a valid, generated OpenAPI schema; `[server]` extra does **not**
   install torch/transformers.
4. SSRF guard is on and not settable per-request; server binds `127.0.0.1` by
   default and requires `GNOSIS_API_TOKEN` when exposed beyond loopback.
5. `gnosis/integrations/llm.py` is importable with no heavy deps; the three
   §6 defects (module-top imports, frontmatter noise, `do_sample=True`) are fixed
   and covered by tests.
6. `qmd.py` + `llm.py` behaviors in §7 are pinned by hermetic tests in the
   **default** CI (no torch, no `qmd` binary); the `test_documents.py`
   inverted-skip anti-pattern is fixed.
7. `qmd`/`llm` failure degrades to a distinct `error.code`/skip; it can never
   take down `/scrape` or `/crawl`; a hung `qmd` subprocess times out.
8. `/v1/crawl` returns a result bundle (md + chunks + manifest + llms.txt +
   WARC), retrievable by job id.
