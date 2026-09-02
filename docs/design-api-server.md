# Design — HTTP server / API mode (+ llm/qmd test coverage)

Status: proposal (design panel, `api-arch` persona)
Scope: minimal server mode for gnosis; test strategy for the optional
`llm`/`qmd` integrations.

---

## 1. Positioning and hard constraints

The server is **not** a rewrite of the pipeline. It is a thin ASGI shell over
the existing async core (`Downloader`, `Crawler`, `HTMLToMarkdownConverter`,
`chunk`, `provenance`, `llms`, optional `qmd`/`llm`). The moat is unchanged:
**markdown is a projection; raw bytes + WARC are the source of truth.** The
server must expose that contract, not hide it.

A scraper server is a **SSRF amplifier** and an abuse vector by construction.
Three rules are non-negotiable:

1. **SSRF guard always on.** `allow_private_network` is opt-in and disabled by
   default. A server that lets a client reach `169.254.169.254` or RFC-1918
   space is a vulnerability, not a feature.
2. **Bind loopback by default.** `--host 127.0.0.1`. Binding `0.0.0.0` is an
   explicit opt-in and prints a warning.
3. **The API is authenticated.** A shared secret (`GNOSIS_API_TOKEN`, sent as
   `Authorization: Bearer <token>`) gates every route when set. Otherwise the
   server is an unauthenticated proxy for arbitrary outbound scraping.

These mirror the project's existing "secure by default" spine (`network.py`).

---

## 2. Framework decision — Starlette + uvicorn, not FastAPI, not aiohttp

**Recommendation: Starlette + uvicorn as an optional extra `[server]`.**

| Option | Verdict |
| --- | --- |
| FastAPI + pydantic | Too heavy. pydantic v2 pulls a Rust-compiled core; we already validate config with plain dataclasses (`config/settings.py`). FastAPI is a superset — adoptable later without throwaway. |
| aiohttp | Duplicates the HTTP stack. The client is already `httpx`; running an aiohttp server means two async HTTP worlds in one process. |
| stdlib `http.server`/`asyncio` | No routing, no streaming, no middleware; we would reinvent and get it wrong. |
| **Starlette + uvicorn** | MIT, ASGI-native, tiny. Crucially, `starlette.testclient.TestClient` is built on **httpx — already a hard dependency** — so API tests stay hermetic with no new test deps. |

```toml
# pyproject.toml
[project.optional-dependencies]
server = ["starlette>=0.37", "uvicorn>=0.30"]
```

Entry point: `gnosis-serve = "gnosis.server:main"`.

### Async model

- **One asyncio event loop** (uvicorn) hosting **one shared `Downloader`** for
  the process lifetime (created in `lifespan`, closed on shutdown). The
  `Downloader` already holds a single `httpx.AsyncClient` connection pool and a
  rate-limit lock — it is designed for concurrent use. One shared client means
  connection reuse and a single robots.txt/politeness clock.
- **`HTMLToMarkdownConverter` is stateful** (`self.stats` is mutated per
  conversion) — instantiate **per request**, never share.
- **Concurrency bound:** a global `asyncio.Semaphore(max_concurrency)`
  (default = `crawler.concurrent_requests`) wraps the work. When the semaphore
  is exhausted, return **429 + `Retry-After`** rather than queueing — a scraper
  that silently queues hides upstream timeouts behind client timeouts.
- **Streaming, not buffering.** `/crawl` returns `StreamingResponse` of
  newline-delimited JSON (NDJSON) fed by `Crawler.crawl()`'s `AsyncIterator`.
  The client sees page 1 while page 20 is still fetching. This is the whole
  point of exposing a crawler over HTTP.
- **Cancellation is cheap.** Starlette propagates client disconnects; the
  shared downloader is not torn down per request, so a cancelled `/crawl`
  leaves the pool warm.
- **Timeouts:** every job carries a `timeout` (seconds), capped by the server's
  `max_job_timeout` (default 300). The `Downloader` keeps its per-fetch timeout
  + retry/backoff as the inner bound.

---

## 3. Endpoints

Minimal surface — 5 routes.

| Method + path | Purpose |
| --- | --- |
| `GET /healthz` | Liveness. No side effects. |
| `GET /readyz` | Readiness: downloader alive + optional `qmd` presence. |
| `POST /fetch` | One URL → markdown + provenance (+ optional chunks). |
| `POST /crawl` | Crawl → streaming NDJSON of pages + summary; writes llms.txt. |
| `POST /index/qmd` | Optional: QMD collection + LLM context + embed. |

### `GET /healthz`

```
200 {"status":"ok","version":"1.3.0"}
```

### `GET /readyz`

```
200 {"ready":true,"qmd_available":true|false}
```
`503 {"ready":false}` if the downloader client is not yet/closed.

### `POST /fetch`

Request:

```json
{
  "url": "https://docs.example.com/page",
  "headers": {"X-Foo": "bar"},
  "bearer_token_env": "TOKEN_VAR",
  "basic_user": "me@example.com",
  "basic_token_env": "PAT_VAR",
  "allow_private_network": false,
  "render": false,
  "warc": false,
  "chunk": false,
  "frontmatter": true,
  "frontmatter_extra": {"tags": ["docs"]},
  "timeout": 60
}
```

Response `200`:

```json
{
  "requested_url": "https://docs.example.com/page",
  "final_url": "https://docs.example.com/page",
  "status_code": 200,
  "fetched_at": "2026-09-02T08:41:44Z",
  "markdown": "# Title\n\n…",
  "content_hash": "<sha256 of markdown>",
  "bytes_sha256": "<sha256 of raw response bytes>",
  "provenance": { "…": "full frontmatter dict (title/url/etag/last_modified/…)" },
  "chunks": [ {"chunk_id":"c0","heading_path":["Title"],"start":0,"end":812,"char_count":812} ]
}
```

`?format=markdown` (or `Accept: text/markdown`) returns the raw document
string, provenance frontmatter included unless `frontmatter:false`.

Error codes:

| Code | Meaning |
| --- | --- |
| 400 | malformed JSON / missing `url` / invalid URL / option above server cap |
| 401 | missing or wrong API token |
| 403 | `robots_disallowed` or `private_network_blocked` (distinguished in `{"error":…,"code":…}` body) |
| 429 | concurrency limit reached (`Retry-After`) |
| 502 | upstream fetch failed after retries |
| 504 | upstream timeout |

### `POST /crawl`

Request:

```json
{
  "url": "https://docs.example.com/",
  "max_depth": 5,
  "max_pages": 100,
  "concurrent_requests": 4,
  "chunk": true,
  "warc": true,
  "llms": true,
  "timeout": 300
}
```

`max_pages`/`max_depth`/`concurrent_requests` may only be *lowered*; the server
caps them (see §4). Response is **streaming NDJSON** (default) or a buffered
manifest (`Accept: application/json`).

NDJSON event stream:

```
{"type":"page","url":"…","file":"…","content_hash":"…","status_code":200,"title":"…","fetched_at":"…"}
{"type":"page", …}
{"type":"summary","saved":42,"skipped":2,"duplicate":1,"failed":["…"],"llms_txt":true,"llms_full_txt":true}
```

Files (markdown, `.chunks.json`, WARC, `_manifest.json`, `llms.txt`,
`llms-full.txt`) are written to a **server-side output dir** derived from the
URL (reuse `url_to_filename`), never from a client-supplied path.

### `POST /index/qmd` (optional)

Request:

```json
{ "url": "https://docs.example.com/", "collection_name": null, "context": null }
```

- `501 {"error":"qmd extra not installed"}` when the `[server,qmd]` extras or
  the `qmd` binary are absent.
- `200` on success: `{"collection":"docs-example-com","context_description":"…","embedded":true}`.
- `collection_name` defaults to `url_to_collection_name(url)`; `context` (if
  supplied) skips the local LLM and goes straight to `qmd context add`.

---

## 4. Security & limits (the part that matters)

- **SSRF guard on every outbound hop** — already enforced by
  `PinnedNetworkBackend` in `network.py`; the server merely refuses to flip the
  default. `allow_private_network` is accepted per-request but the server may
  hard-disable it (env `GNOSIS_SERVER_ALLOW_PRIVATE_NETWORK=false` default).
- **Auth:** `GNOSIS_API_TOKEN` env → require `Authorization: Bearer <token>` on
  every route. Unset = no auth (still loopback-bound, so acceptable for a
  local tool).
- **Server caps** (`config`/env): `max_pages`, `max_depth`, `max_concurrency`,
  `max_job_timeout`, `max_body_bytes` (default 64 KiB). Client values above a
  cap are clamped **down** (or 400 — opinion: clamp `max_pages`, reject
  oversized bodies).
- **No client paths.** `output_dir`/`collection_name` are derived server-side
  from the URL (reuse `url_to_filename`/`url_to_collection_name`) and rooted at
  a configured `output_root`. Prevents path traversal.
- **robots.txt stays on** (the `Downloader` already respects it + Crawl-delay).
- **URL length + scheme whitelist:** `http`/`https` only.

---

## 5. Required refactor: extract the pipeline from the CLI

`cli/main.py` currently entangles the pipeline with `console`, `click`, and
`sys.exit` (`download_and_convert`, `crawl_and_convert`, `run_qmd_integration`
print directly and call `sys.exit`). The server cannot reuse those as-is
without forking them.

**Move the pipeline into `gnosis/service.py`** (pure, no Click/Rich):

```python
@dataclass
class PageResult:
    url: str
    final_url: str
    markdown: str
    document: str            # rendered w/ provenance (or bare)
    content_hash: str
    bytes_sha256: str
    provenance: dict
    chunks: list[dict]       # [] unless chunk=True
    fetch: FetchResult

async def convert_fetch(fetch, settings, *, renderer=None, verbose=False) -> PageResult
async def fetch_page(url, settings, **opts) -> PageResult          # wraps Downloader
async def crawl_pages(url, settings, **opts) -> AsyncIterator[PageResult]
```

The CLI becomes a thin reporter that consumes `PageResult` and prints; the
server consumes the same `PageResult` and serializes it. `run_qmd_integration`
is refactored to return a result object instead of printing (it already
lazy-imports `LLMContextGenerator`/`QMDIntegrator` — keep that).

This is the single most important architectural move: **one pipeline, two
front-ends.**

---

## 6. Test coverage for the optional llm/qmd integrations

Current state: `integrations/llm.py` and `integrations/qmd.py` have **zero**
tests. `llm.py` hard-imports `torch` and `transformers` at module top, so it
can't even be imported without the `[qmd]` extras. Fix the testability bug
first, then test hermetically — **CI never installs torch or the `qmd`
binary.**

### 6.1 Make `llm.py` import-safe (prerequisite)

Move `import torch` / `from transformers import …` **into `_load_model()`**
(mirroring `integrations/documents.py`, which already lazy-imports MarkItDown,
and `run_qmd_integration`, which already lazy-imports `LLMContextGenerator`).
Then every pure helper is unit-testable with zero heavy deps.

### 6.2 `tests/test_llm_integration.py`

Pure helpers (no model):

- `_aggregate_content`
  - respects `sample_files_limit` (only first N files read);
  - respects `sample_content_max_chars` + appends `\n[... truncated ...]`;
  - single-file input strips the `## File:` header;
  - unreadable file is skipped (monkeypatch `Path.read_text` to raise);
  - empty dir → `"No content available."`;
  - `> max_files` appends `[Note: Showing N of M files]`.
- `_create_messages` → `[{"role":"user","content":…}]`.
- `_clean_thinking_tags` → strips multiline `<think>…</think>`, collapses blank
  lines, strips whitespace.
- `/no_think` suffix appended **only** when `"qwen"` in `llm_model.lower()`.

Orchestration with a **faked model** (monkeypatch the transformer entry points,
no weights):

- stub `AutoTokenizer.from_pretrained` / `AutoModelForCausalLM.from_pretrained`;
- stub `apply_chat_template` returns a dict with an `input_ids` tensor;
- stub `generate` returns a tensor of extra tokens that decode to a canned
  string with a `<think>` block;
- assert `generate_context` returns the cleaned description, passes the
  prompt through `apply_chat_template` as user-role messages, and calls
  `cleanup()`.
- failure path: `_load_model` raising → `generate_context` raises
  `RuntimeError("Failed to load LLM model: …")`.

A **real-model smoke test** is opt-in only: `@pytest.mark.skipif(not os.getenv("GNOSIS_LLM_SMOKE"), …)`
— never in default CI.

### 6.3 `tests/test_qmd_integration.py`

`QMDIntegrator` shells out via `subprocess.run` — fully testable with a fake
`subprocess`/`_run_command` and `shutil.which` monkeypatch, no `qmd` binary:

- `_verify_qmd_installed` → `QMDNotFoundError` when `shutil.which("qmd")` is
  `None`; passes when present.
- `_run_command` → passthrough on success; `CalledProcessError` →
  `QMDCommandError` whose message includes exit code + stderr.
- `add_collection` → exact argv
  `["qmd","collection","add",<resolved dir>,"--name",<name>,"--mask","**/*.md"]`;
  the `"already exists"` branch parses the existing name
  (`_parse_existing_collection_name`), calls `remove_collection`, retries, and
  raises `QMDCommandError` if the retry fails.
- `_parse_existing_collection_name` → extracts `Name: foo`; returns `None` when
  absent.
- `remove_collection` / `add_context` / `embed` → argv correctness via a
  recording fake.
- `embed(force=True)` appends `-f`.
- `run_pipeline` → asserts call **order**: add_collection → add_context → embed.
- `collection_exists` → `False` when `qmd collection list` raises.

### 6.4 `tests/test_server_index.py` (the optional route)

- `POST /index/qmd` returns **501** when extras/binary missing.
- With a **fake `QMDIntegrator` + `LLMContextGenerator` injected through the
  app factory** (dependency injection, not monkeypatching), returns `200` with
  the collection name + description; assert the pipeline order.
- `401` without token (when `GNOSIS_API_TOKEN` set); `400` on bad body.

### 6.5 `tests/test_server.py` (core routes)

Using `starlette.testclient.TestClient` (httpx under the hood) against
localhost fixture servers (same pattern as `test_cli.py`/`test_llms.py`):

- `GET /healthz` → 200.
- `GET /readyz` → 200, `qmd_available` false/true.
- `POST /fetch` → 200 with `markdown` + `bytes_sha256` + `content_hash` +
  `provenance`; `?format=markdown` returns the raw doc.
- `POST /fetch` against the SSRF fixture → **403 `private_network_blocked`**
  even with a redirect chain (guard fires per hop).
- `POST /crawl` → streams ≥1 `type=page` event then a `summary`; `llms.txt`
  written.
- `429` when concurrency semaphore saturated (seed with a slow fixture).
- `401` when token missing/invalid.
- `400` missing url / oversized body; `502` on upstream 500-after-retries.

Gating: server tests begin with `pytest.importorskip("starlette")` so the
default `pip install -e '.[test]'` suite still passes offline without the
`[server]` extra; CI adds a matrix leg running `.[test,server]`.

---

## 7. Explicitly out of scope (v1)

- Job queues, persistence, webhooks (ROADMAP already defers to v2).
- FastAPI/pydantic (revisit only if OpenAPI/schema becomes a requirement).
- WebSocket streaming.
- Binding `0.0.0.0` or unauthenticated remote exposure by default.
- Any endpoint that accepts arbitrary client filesystem paths.
