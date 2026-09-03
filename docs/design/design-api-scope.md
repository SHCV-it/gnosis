# Design — API mode: scope discipline + llm/qmd test coverage

Panel item: **api-scope**. Author: scope/positioning panel member. Status: proposal.

Scope: `gnosis/cli/main.py` (service-layer split), `gnosis/service.py` (new),
`gnosis/integrations/llm.py`, `gnosis/integrations/qmd.py`, `tests/`,
`pyproject.toml` (`[server]` extra), `README.md`.

Related docs: `design-api-server.md` (api-arch persona) and
`design-server-api-mode.md` (api-sre persona). This doc is the **scope**
position: it draws the line between "gnosis the OSS repo" and "gnosis the
product," and pins the minimum test contract for the optional integrations.
Where I disagree with the other two docs, I say so explicitly in §7.

---

## Verdict

Do **two things in the repo**, and **one thing out of it**.

1. **In the repo:** extract a pure, async *service layer* out of
   `gnosis/cli/main.py` and ship a **reference** HTTP server as an optional
   `[server]` extra. The service layer is a library-quality refactor of code
   that already exists; the reference server proves the seam and serves the
   "self-hostable" claim without pretending to be a product.
2. **In the repo:** make `integrations/llm.py` import-safe and give
   `llm.py`/`qmd.py` stubbed unit tests that enforce one contract —
   *a missing or failing optional integration degrades gracefully; the scrape
   output is never lost and the process never crashes.* Today they have zero
   coverage and `llm.py` cannot even be imported without torch.
3. **Out of the repo (separate product):** multi-tenant auth, quotas/billing,
   the scrape/qmd queue and scale-out, job persistence, webhooks, abuse/legal
   response, and any always-on hosted operation. These are the *product*, not a
   later version of the repo. The repo's only obligation is to leave the
   **seams** that make the product buildable without a rewrite.

---

## 1. The scope line (the point of this doc)

**Rule: the repo ships a tool and a reference; the product ships a service.
The boundary is multi-tenancy and always-on operations.** If a feature's only
justification is "to run this as a public/commercial service," it does not
belong in `gnosis/`.

| Belongs in the OSS repo | Belongs in a separate product |
| --- | --- |
| `gnosis/service.py` — pure async pipeline returning typed results (a refactor of existing CLI code) | Multi-tenant auth (per-API-key identity, quotas, billing) |
| A loopback-bound, single-token **reference** server (`[server]` extra) | Scrape/qmd queue workers (arq/Redis/Celery) + job persistence + webhooks |
| Import-safe `llm.py`, graceful-degrade `qmd.py`, and their stubbed unit tests | GPU pool / hosted LLM for context generation; hosted vector DB |
| Per-host politeness, `subprocess timeout=`, WARC serialization, SSRF guard (already present) | SRE runbooks, abuse/legal response, rate-limit policy across tenants |
| The `[qmd]`/`[docs]` optional extras (self-host tooling) | A hosted "gnosis cloud" API |

The local `qmd`/`llm` integration **stays in the repo** — it is a self-host
capability (QMD CLI + a local HF model), consistent with the offline-first
ethos. What goes out is the *cloud* version of that capability.

---

## 2. The prerequisite refactor: a service layer (non-negotiable, do it first)

Fact-checked in `gnosis/cli/main.py`: `download_and_convert` and
`crawl_and_convert` do fetch → render → convert → `console.print` →
`output_path.write_text` → QMD, and call `sys.exit(1)` on `RobotsDisallowed`,
`PrivateNetworkBlocked`, download failure, *and* "file exists".
`run_qmd_integration` prints everything and returns `None`. None of this is
reusable from any other front-end.

Move it into `gnosis/service.py` — **no `click`, no `rich`, no `sys.exit`,
no `Path`-writing in the happy path.** One pipeline, two front-ends (CLI +
reference server). Concretely:

```python
@dataclass
class PageResult:
    url: str
    final_url: str
    markdown: str            # bare body
    document: str            # markdown + provenance frontmatter (or bare)
    content_hash: str
    bytes_sha256: str
    provenance: dict
    chunks: list[dict]
    fetch: FetchResult

@dataclass
class QmdResult:
    status: str              # "ok" | "skipped:qmd-missing" | "failed:llm" | "failed:qmd"
    collection_name: str | None
    context_description: str | None
    error: str | None

async def convert_fetch(fetch, settings, *, renderer=None, verbose=False) -> PageResult
async def fetch_page(url, settings, **opts) -> PageResult
async def crawl_pages(url, settings, **opts) -> AsyncIterator[PageResult]
async def run_qmd(settings, *, output_dir, url, files) -> QmdResult   # returns, never prints
```

The CLI becomes a thin reporter over `PageResult`/`QmdResult`; the reference
server serializes the same objects. This is the single highest-value change and
is correct **regardless** of the server decision — it is how the library earns
an importable API.

---

## 3. The reference server (what it is, what it is not)

**Framework: Starlette + uvicorn** as `[server]` — not FastAPI, not aiohttp.
I reach the same conclusion as `design-api-server.md` but for a different
reason: the server is a *reference*, so the cheapest ASGI thing that proves the
seam wins. `starlette.testclient.TestClient` is built on **httpx, already a
hard dependency**, so API tests add zero new test deps. Pydantic/OpenAPI is
product scope — adopt it only if the product needs schemas.

```toml
[project.optional-dependencies]
server = ["starlette>=0.37", "uvicorn>=0.30"]
```

**Deliberately smaller surface than the other two docs propose** — a reference
does not need a job queue. Four routes:

| Route | Purpose |
| --- | --- |
| `GET /healthz` | liveness + version; folds in "downloader alive / qmd available" so we skip a separate readyz |
| `POST /fetch` | one URL → `PageResult` JSON (markdown + provenance + both hashes + optional chunks) |
| `POST /crawl` | streaming NDJSON fed by `crawl_pages()`'s `AsyncIterator` |
| `POST /index/qmd` | exercise the optional-integration seam; `501` when extras/binary absent |

**Not in the reference:** `/jobs/{id}`, job persistence, `/metrics`, webhooks,
multi-tenant tokens, per-client quotas. All product.

**Hard defaults for the reference server:**

- Bind `127.0.0.1`; `0.0.0.0` is opt-in and prints a warning.
- Single shared token via `GNOSIS_API_TOKEN` (Bearer). Unset = allowed only
  because loopback-bound; document that an unauthenticated scraper is an open
  proxy.
- `HTMLToMarkdownConverter` is **stateful** (`self.stats` mutated per convert) —
  instantiate per request. The `Downloader` is safe to share (it is already
  concurrency-aware).

---

## 4. Security fence (the moat applies to the API)

1. **SSRF guard is never client-overridable.** `allow_private_network` exists on
   `DownloaderSettings`, and `build_transport` returns `None` (the *unguarded*
   stock httpx transport) when it is set — i.e. the flag **disables** the guard
   wholesale. The server must never accept it per-request; it may only be set
   by the operator. An open scraper API is an SSRF-as-a-service amplifier.
2. **Scheme whitelist** `http`/`https`; URL length cap; no client filesystem
   paths (derive output dir from `url_to_filename`, rooted at `output_root`).
3. **Caps clamp down**: `max_pages`, `max_depth`, `concurrency`, `timeout`,
   `max_body_bytes` — a client may only request *less* than the operator cap.
4. **robots.txt + politeness stay on** (already enforced by `Downloader`).

---

## 5. Two concurrency bugs to fix *before* serving (and one to fix anyway)

These are real, read from the code. The api-sre doc lists four; I agree with
all four and want two of them done in the repo even without the server, because
they bite the CLI too:

1. **Global rate limiter (`gnosis/core/downloader.py`).** `Downloader._rate_limit`
   holds one `_last_request_time` + `_rate_lock` per instance, so a server with
   one shared `Downloader` throttles the *whole service* to one request per
   `rate_limit_ms` (default 500 ms = 2 req/s) regardless of host. Politeness is
   a property of the **target host**, not the process. Fix: key the limiter by
   `netloc`. (A same-domain crawl is unaffected today; the server is not.)
2. **Blocking subprocess / torch in the event loop (`integrations/qmd.py`,
   `integrations/llm.py`).** `QMDIntegrator._run_command` uses
   `subprocess.run(capture_output=True, ...)` with **no `timeout=`**, and
   `LLMContextGenerator.generate_context` runs HF inference synchronously. Both
   block an asyncio loop. Fix: `timeout=` on every subprocess,
   `asyncio.to_thread()` for QMD + inference, `HF_HUB_OFFLINE` guard.
3. **WARC writer is not concurrency-safe (`gnosis/core/archive.py`).** One
   `_warc_file` opened in `ab` + one `WARCWriter(gzip=True)` per `Archiver`;
   interleaved writes corrupt the gzip. The content-addressed store is already
   safe (unique-hash blobs). Fix: per-job `Archiver` + per-job output dir in the
   server (the reference does not need cross-job store dedup — that is product).

The fourth api-sre item (job persistence / graceful drain) is **product scope**
and I do not gate the reference server on it: with no job queue, there are no
in-flight jobs to persist, and uvicorn's lifespan hook can drain the shared
`Downloader`.

---

## 6. Test coverage for the optional llm/qmd integrations

**The contract every optional integration must honor:**

> A missing dependency or a failed integration must degrade gracefully — the
> core scrape output is never lost, and the process never crashes.

### 6.1 Fix the import-safety bug first (prerequisite)

`gnosis/integrations/llm.py` does `import torch` and
`from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer` at
**module top**, so the module cannot be imported without the `[qmd]` extra. This
contradicts `integrations/__init__.py`'s own docstring ("heavy dependencies…
not loaded until `--qmd-index` is used") — the laziness is one level too
shallow. Move those imports **into `_load_model()`**, mirroring
`integrations/documents.py` (which already lazy-imports MarkItDown). Then every
pure helper is unit-testable with zero heavy deps.

### 6.2 The naming trap

`tests/test_llms.py` tests `llms.txt` — **not** the LLM integration. Anyone
greping "llm test coverage" will think it's covered when it isn't. Add
`tests/test_llm_integration.py` and `tests/test_qmd_integration.py` so the gap
is visible by filename.

### 6.3 Do not copy the `test_documents.py` anti-pattern

`tests/test_documents.py` sets `pytestmark = skipif(find_spec("markitdown") is
not None, ...)` — so the *negative* path only runs when markitdown is absent,
and the *positive* path is never exercised at all. The result is an optional
integration with effectively no CI coverage in either configuration. For
`llm.py`/`qmd.py` the rule is: **stub the heavy dependency, never skip on its
presence.**

### 6.4 The minimum matrix (all offline, no torch in default CI)

`qmd.py` — monkeypatch `shutil.which` + `subprocess.run`:

- `_verify_qmd_installed` → `QMDNotFoundError` when `which("qmd")` is `None`.
- `_run_command` → `QMDCommandError` on non-zero exit with exit code + stderr in
  the message; assert a `timeout=` is passed (this is the bug fix, test it).
- `add_collection` exact argv; `"already exists"` → parse name
  (`_parse_existing_collection_name`) → `remove_collection` → retry; retry fail
  → `QMDCommandError`.
- `embed(force=True)` appends `-f`; `run_pipeline` asserts order
  add_collection → add_context → embed.

`llm.py` — stub `torch`/`transformers` in `sys.modules` (or mock the entry
points), no weights:

- `_aggregate_content`: `max_chars` truncation + `[... truncated ...]`;
  `sample_files_limit`; empty → `"No content available."`; single-file header
  stripped; `> max_files` → `[Note: showing N of M files]`.
- `_clean_thinking_tags`: strips multiline `<think>…</think>`, collapses blank
  lines.
- `_create_messages` → `[{"role":"user","content":…}]`.
- `/no_think` appended **only** when `"qwen"` in `llm_model.lower()`.
- `_load_model` raising → `generate_context` raises
  `RuntimeError("Failed to load LLM model: …")`.
- `cleanup()` deletes model/tokenizer and calls `torch.cuda.empty_cache()` when
  CUDA is present.

Integration seam (`run_qmd` in `service.py`, replacing `run_qmd_integration`):

- QMD missing → `QmdResult(status="skipped:qmd-missing")`, scrape output intact.
- LLM generation fails (license not accepted) → `status="failed:llm"`, output
  intact.
- Full success → `run_pipeline` called with the right collection name + context.

CI: stubbed tests run in the **default** leg (no torch). A real-model smoke
test is `@pytest.mark.skipif(not os.getenv("GNOSIS_LLM_SMOKE"))` — never in
default CI. Server tests start with `pytest.importorskip("starlette")` so the
core `.[test]` install stays green without `[server]`.

---

## 7. Where I disagree with the other two docs

- **api-sre §5 (arq/Redis two-queue, Docker/K8s, Prometheus metric names) is
  product scope, not repo scope.** The repo's job is to leave the *seams* —
  typed `PageResult`/`QmdResult`, one-model-load-per-process, `timeout=` on
  subprocesses, serialized WARC. Choosing arq vs Celery, defining
  `gnosis_scrape_*` counters, and writing K8s manifests is exactly the work the
  separate product should own. Writing it into the repo doc invites it into the
  repo.
- **api-arch §2 (Starlette not FastAPI) — agree with the outcome, different
  reasoning.** It's not primarily that pydantic is heavy; it's that a reference
  server must be the cheapest proof of the seam. FastAPI would only be justified
  by product schemas/OpenAPI, which are product.
- **api-arch §3 wants `/jobs`-style job semantics and api-sre §2 wants a
  `/jobs/{id}` + `/result` bundle. Both are product.** The reference server
  should be request/response + streaming; a job queue is the first feature that
  crosses the multi-tenant/always-on line.

---

## 8. Acceptance criteria

1. `gnosis/service.py` exposes `fetch_page`/`crawl_pages`/`run_qmd` returning
   typed results; the CLI is a thin printer over them (no `sys.exit`/`console`
   in the service); existing CLI tests still pass unchanged.
2. `gnosis/integrations/llm.py` imports cleanly **without** torch installed;
   torch/transformers imports live inside `_load_model()`.
3. `pip install gnosis-markdown[server]` boots `/healthz`, `/fetch`, `/crawl`,
   `/index/qmd` bound to `127.0.0.1`; core install untouched.
4. SSRF guard active by default; no request field can enable private-network
   fetch; `allow_private_network` is operator-config only.
5. `llm.py` + `qmd.py` reach ≥85% line coverage via stubbed tests in the
   **default** CI (no torch); `test_llm_integration.py` /
   `test_qmd_integration.py` exist and do not skip on dependency presence.
6. Optional-integration failures degrade to a `QmdResult` status string with the
   scrape output preserved; covered by tests.
7. Per-host rate limiting and subprocess `timeout=` are in place and tested.
8. `README.md` states the boundary explicitly: reference server in-repo,
   multi-tenant/queued API is a separate product.
