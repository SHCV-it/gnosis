# Design — HTTP server/API mode + llm/qmd test coverage + scale/queue model

Panel item: **api-sre**. Author: SRE panel member. Status: proposal.
Scope: `gnosis/cli/main.py` (orchestration decoupling), a new `gnosis/api/`
package, `gnosis/core/downloader.py`, `gnosis/core/archive.py`,
`gnosis/integrations/llm.py`, `gnosis/integrations/qmd.py`, `tests/`,
`pyproject.toml` (new `server` extra), `.github/workflows/ci.yml`.

## Verdict

Gnosis is a **CLI-only** product today. Every orchestration function in
`gnosis/cli/main.py` (`download_and_convert`, `crawl_and_convert`,
`run_qmd_integration`) is hard-wired to `rich.console.print`, `sys.exit(1)`,
and the `Path`-based output dir — there is **no service layer** that returns a
structured result. You cannot bolt an HTTP API onto this; you must first split
it. The good news: the download/conversion core is already clean and async, so
the refactor is *mechanical*, not architectural.

My recommendation: **(1) extract one async service layer, (2) put FastAPI in
front of it as an optional `[server]` extra, (3) fix four concrete
async-concurrency bugs before anything is served, (4) cover `llm.py`/`qmd.py`
with dependency-stubbed unit tests — today they have *zero* coverage — and (5)
ship a single-process server first, then a two-queue (scrape / qmd) worker
model, with a strict "SSRF guard is never client-overridable" rule.**

This is consistent with ROADMAP's "Distributed queue/webhooks/cluster in v2":
I am not proposing to build the cluster now. I am proposing the *seams* now so
the v2 scale-out is a deployment change, not a rewrite.

---

## 1. The coupling problem (exactly where it is)

- `download_and_convert(url, settings, quiet, verbose)` (main.py) does fetch →
  render → convert → `console.print` → `output_path.write_text` → QMD, and
  calls `sys.exit(1)` on `RobotsDisallowed`, `PrivateNetworkBlocked`, download
  failure, *and* "file exists". None of that is reusable from a server.
- `crawl_and_convert` additionally mutates a checkpoint/manifest on disk,
  writes `llms.txt`/`llms-full.txt`, and calls `sys.exit(1)` when zero pages
  saved. Same problem.
- `run_qmd_integration` swallows everything into `console.print` and returns
  `None` — a server needs *machine-readable* success/failure ("skipped: qmd
  missing", "failed: llm license not accepted").

The fix is one move: introduce `gnosis/service.py` with a `ScrapeService` /
`CrawlService` that takes a `Settings` and returns typed dataclasses; the CLI
becomes a thin printer over it. **One service, two front-ends (CLI + HTTP).**

---

## 2. API surface (concrete)

Framework: **FastAPI + uvicorn**, shipped as `gnosis-markdown[server]`
(`fastapi`, `uvicorn`) and imported lazily inside `gnosis/api/` so CLI users
never pay for it. FastAPI is asyncio-native (matches the httpx core), gives
OpenAPI docs for free, and Pydantic gives request validation.

| Method | Path | Purpose | Returns |
| --- | --- | --- | --- |
| `POST` | `/v1/scrape` | one URL → markdown, synchronous | 200 `ScrapeResult` (markdown + provenance + `bytes_sha256`/`content_hash`) |
| `POST` | `/v1/crawl` | async crawl job | 202 `{job_id}` |
| `GET` | `/v1/jobs/{job_id}` | job status | `{status, pages_done, pages_failed, error}` |
| `GET` | `/v1/jobs/{job_id}/result` | result bundle | `{manifest, files[], llms_txt, chunks}` or a `.tar.gz`/NDJSON stream |
| `GET` | `/healthz` | liveness (process up) | `200` |
| `GET` | `/readyz` | readiness (disk writable, redis reachable, qmd binary present iff enabled) | `200`/`503` |
| `GET` | `/metrics` | Prometheus | text |

Request body for `/v1/scrape`:

```json
{
  "url": "https://docs.python.org/3/",
  "all": false,
  "chunk": true,
  "warc": true,
  "render": false,
  "qmd_index": false,
  "max_pages": 500,
  "max_depth": 10
}
```

**Every field is optional** and defaults come from `Settings` — the API never
allows more than the operator's configured caps (`max_pages`, `max_depth`
clamped server-side). `allow_private_network` is **not** accepted from clients
(see §6).

---

## 3. Four async-concurrency bugs to fix before serving (SRE non-negotiables)

These are real, from reading the code, and each one becomes a production
incident the day a server ships:

1. **Global rate limiter.** `Downloader._rate_limit` uses a single
   `_last_request_time` + `_rate_lock` per instance. A server processing 10
   URLs across 10 different hosts would throttle the *whole service* to one
   request per 500 ms (2 req/s). Fix: key the limiter **per origin
   (`netloc`)** — politeness is a property of the *target host*, not of the
   process. (`gnosis/core/downloader.py`)

2. **Blocking subprocess + torch in the event loop.** `QMDIntegrator._run_command`
   uses `subprocess.run(capture_output=True, ...)` with **no `timeout=`**, and
   `LLMContextGenerator.generate_context` runs torch inference synchronously.
   In an asyncio server both block the loop and hang a worker on a wedged `qmd`
   or a stuck HF model download. Fix: `asyncio.to_thread()` for the QMD pipeline
   and LLM inference, `timeout=` on every subprocess, and an explicit
   `HF_HUB_OFFLINE`/model-cache guard. (`integrations/qmd.py`, `integrations/llm.py`)

3. **WARC writer is not concurrency-safe.** `Archiver` opens `archive.warc.gz`
   in append mode and keeps **one** `_warc_file` per instance; two concurrent
   jobs interleave gzip members and corrupt the WARC. Fix: per-job output
   directory, or a single writer task, or `asyncio.Lock` around the WARC writer.
   The content-addressed store is already safe (unique-hash blobs) — the WARC
   is not. (`gnosis/core/archive.py`)

4. **No job persistence / graceful drain.** In-flight jobs die on restart.
   Acceptable for v1 *only because* every job is idempotent and content-addressed,
   but shutdown must still drain in-flight `asyncio` tasks, `await
   downloader.close()`, and flush the WARC. Wire that into uvicorn's
   lifespan/shutdown hook.

---

## 4. Test coverage for the optional llm/qmd integrations (currently zero)

Fact: there is **no** `tests/test_llm.py` and **no** `tests/test_qmd.py`.
`tests/test_llms.py` is about `llms.txt` (core), not the LLM integration.
`tests/test_documents.py` covers only the *absent* dependency path, and its
`skipif` skips when markitdown **is** installed — so the positive path is
never exercised in CI and the negative test doesn't run in the `[docs]`-installed
leg. That's the pattern to fix, not copy.

**The contract to enforce for every optional integration:**
> Absent dependency or failed integration must degrade gracefully — the core
> scrape output is never lost, and the process never crashes.

Test matrix (all **offline**, heavy deps stubbed — no torch in default CI):

### `qmd.py` (mock `subprocess.run` + `shutil.which`, no real qmd binary)
- `_verify_qmd_installed` raises `QMDNotFoundError` when `shutil.which` → `None`.
- `_run_command` raises `QMDCommandError` on non-zero exit, with stderr in the message.
- `add_collection`: success; "already exists" → parse name → remove → retry success;
  retry still failing → `QMDCommandError`.
- `_parse_existing_collection_name` regex (`Name:\s+(\S+)`).
- `add_context`, `embed` (`-f` flag), `run_pipeline` — assert exact command lists.
- `collection_exists` True/False.

### `llm.py` (stub `torch`/`transformers` in `sys.modules` via `conftest.py`)
- `_aggregate_content`: `max_chars` truncation + `[... truncated ...]`;
  `max_files` sampling; empty → `"No content available."`; single-file header
  stripped; `"Note: showing N of M files"` when sampled.
- `_clean_thinking_tags`: strips multiline `<think>...</think>`, collapses blank lines.
- `generate_context`: with `_load_model`/`_generate` mocked — prompt built from
  `context_prompt_template`, `/no_think` appended only for qwen model names,
  and errors wrapped in `RuntimeError`.
- `_load_model` failure → `RuntimeError("Failed to load LLM model: ...")`.
- `cleanup` deletes `model`/`tokenizer` and calls `torch.cuda.empty_cache()` when CUDA present.

### Integration seam (`cli/main.py` → `run_qmd_integration`)
- QMD not installed → graceful skip, exit 0, scrape output intact.
- LLM generation fails (e.g. license not accepted) → graceful skip, exit 0.
- Full success → `run_pipeline` invoked with the right collection name + context.

### CI legs
- **Default (fast, offline):** the stubbed unit tests above. No torch pulled.
- **Optional/nightly `qmd-integration` job:** installs `[qmd]` + a real `qmd`
  binary + a tiny model, runs `@pytest.mark.integration` tests. Gated, not on
  every push (torch ≈ multi-GB).

---

## 5. Scale / queue / deployment model

**Phase 1 — single-process uvicorn (0 → dozens of concurrent jobs).**
In-process `asyncio` job store (`dict` + tasks), concurrency bounded by a
semaphore (`api.max_concurrent_jobs`), results written to the content-addressed
store + per-job output dirs. This is the v1 target and matches the
self-hostable/offline ethos. No Redis yet.

**Phase 2 — two-queue workers (scale-out).**
Split work by *resource profile*, not by URL:

| Queue | Workload | Worker profile |
| --- | --- | --- |
| `scrape` | httpx fetch → convert → provenance → WARC | CPU/network, high concurrency, horizontal scale |
| `qmd` | LLM context generation + `qmd` subprocess | torch model loaded **once per worker process** (`_load_model` is already guarded by `_model_loaded` — keep that), `concurrency=1` per worker, GPU affinity |

Queue tech: **arq** (asyncio-native, Redis-backed) is my pick over Celery — the
codebase is asyncio end-to-end, and arq is a ~1-dep fit. Backpressure via queue
depth; job state in Redis; workers scale horizontally and independently. The
`qmd` queue is *separate* precisely so a 2 GB model load or a hung `qmd` subprocess
can never starve scrape throughput.

**Deployment:**
- **Docker:** multi-stage `python:3.12-slim`, non-root user, read-only rootfs +
  tmpfs for scratch, `GNS_*` env vars only (the existing `${ENV_VAR}` pattern
  maps 1:1 to 12-factor config — add an env-var config loader that produces a
  `Settings`).
- **Kubernetes:** API `Deployment` (HPA on request latency + CPU), `scrape`
  worker `Deployment`, `qmd` worker `Deployment`, Redis managed/StatefulSet,
  PVC (or S3-compatible sink) for WARC + store.
- **Health/readiness:** `/healthz` = process alive; `/readyz` = disk writable,
  Redis reachable, `qmd` binary present only when `qmd.enabled`.
- **Observability:** structured JSON logs (drop Rich in the server path), request
  IDs, and Prometheus metrics — `gnosis_scrape_duration_seconds`,
  `gnosis_scrape_bytes`, `gnosis_jobs_total{status}`, `gnosis_queue_depth`,
  `gnosis_ssrf_blocks_total`, `gnosis_rate_limit_wait_seconds`. The SSRF-block
  and rate-limit-wait counters are the two that matter for a scraper service.

---

## 6. Security posture (the moat applies to the API too)

- **SSRF guard stays on by default, and is never client-overridable.** An open
  scraper API is an SSRF-as-a-service amplifier. `allow_private_network` may only
  be set by the *operator* via server config (`api.allow_private_network: true`),
  never per-request. `PinnedNetworkBackend` + `build_transport` already enforce
  this — do not add a request field that bypasses it.
- **API auth:** `--api-token-env` (Bearer), consistent with the existing
  `${ENV_VAR}` secret convention. Optional, but document loudly that an
  unauthenticated scraper API is an open proxy.
- **Per-client rate limiting** on top of the per-host politeness limiter.
- **Output-size / page-count caps** (clamp `max_pages`, `max_depth`, WARC bytes)
  to bound disk and memory.

---

## 7. What we deliberately skip (v2, not now)

- Webhooks/callbacks — polling is enough for v1.
- Multi-tenant / API-key billing.
- Browser cluster as core (render stays a sidecar subprocess).
- Any mandatory cloud dependency — stays offline-first.

## 8. Acceptance criteria (for the eventual issue)

1. `gnosis.service.ScrapeService`/`CrawlService` return typed results and are
   called by *both* the CLI and the API (CLI is a thin adapter; no `sys.exit`
   or `console` in the service).
2. `pip install gnosis-markdown[server]` + `gnosis-server` boots `/v1/scrape`
   and `/v1/crawl`; core install untouched.
3. SSRF guard active by default in the server; no request path can enable
   private-network fetch.
4. `qmd.py` + `llm.py` reach ≥85% line coverage via dependency-stubbed unit
   tests in the **default** CI (no torch downloaded).
5. QMD/LLM failures degrade to a graceful skip with the scrape output preserved.
6. Per-host rate limiting, subprocess `timeout=`, and WARC writer serialization
   are in place and covered by tests.
7. `/healthz`, `/readyz`, `/metrics` emit the six metrics in §5.
