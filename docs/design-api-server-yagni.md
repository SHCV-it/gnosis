# Design — API mode verdict (YAGNI persona)

Panel item: **api-yagni**. Status: verdict.
Scope: whether to build HTTP server/API mode now, and what test coverage the
optional `llm`/`qmd` integrations actually need.

---

## Verdict (one sentence)

**Do not build the HTTP server now — it is a distraction from the moat — but
DO write hermetic tests for `llm.py`/`qmd.py` now, because those modules ship
today with zero coverage and one hard import bug.**

Server mode: **NO (defer).** llm/qmd test coverage: **YES (do immediately).**

---

## 1. The three facts that decide this

1. **There is no demand signal for a server.** The roadmap explicitly defers
   it — *"Distributed queue/webhooks/cluster in v1 — v2"* — and lists it under
   *"What we deliberately skip."* The README's entire positioning is CLI +
   offline + self-hostable auditability. Nothing in the issue checklist is an
   API. An HTTP API is speculative until a user files the issue.

2. **The panel itself cannot agree on the API surface.** There are already
   three design docs in this repo and they disagree on fundamentals:

   | Decision | `design-api-server.md` | `design-server-api-mode.md` | `design-api-server-security.md` |
   | --- | --- | --- | --- |
   | Framework | Starlette + uvicorn | FastAPI + uvicorn | FastAPI/Starlette |
   | Fetch shape | `POST /fetch` → sync 200 | `POST /v1/scrape` → sync 200 | — |
   | Crawl shape | `POST /crawl` → streaming NDJSON | `POST /v1/crawl` → 202 `{job_id}` + `GET /jobs` | — |
   | Scale | single-process only | single → **arq + Redis two-queue** | single-process |

   Three personas, three incompatible architectures. When the panel cannot
   agree on the routes, you do not have the routes — you have a bike-shed.
   Building now means building the wrong thing, then rebuilding it. The
   correct YAGNI move is to *not* pick a framework or a queue now.

3. **The code is not ready to serve, and the gaps are CLI bugs first.** The
   four "async-concurrency" issues the SRE persona found are all real — and
   every one of them bites the **CLI today**, before any server exists:
   - `integrations/qmd.py` `_run_command` → `subprocess.run(..., capture_output=True, ...)` with **no `timeout=`** — a wedged `qmd` hangs the CLI forever.
   - `core/downloader.py` `_rate_limit` keeps **one** global `_last_request_time` + `_rate_lock` — an `--all` crawl is throttled to one request per 500 ms *across all hosts*, so `concurrent_requests: 5` is a lie in practice.
   - `integrations/llm.py` runs synchronous torch inference; `cli/main.py` calls `run_qmd_integration` inline in the asyncio task.

   These are bugs, not server prerequisites. Fix them for the CLI's own sake.

---

## 2. Why a server is a distraction now

- **It's a permanent tax for speculative benefit.** Every endpoint is
  attack surface forever: SSRF amplifier, auth (`GNOSIS_API_TOKEN`), server
  caps (`max_pages`/`max_depth`/body bytes), path-traversal prevention,
  per-client rate limiting. Firecrawl/Crawl4AI/Jina already own "scraper API"
  and are much bigger. Gnosis winning there means competing on their turf;
  gnosis winning on *auditable offline output* means staying CLI-first.
- **The moat is unchanged by a server.** Byte-level SHA-256, WARC, provenance
  frontmatter are all output artifacts — a server neither adds to nor
  deepens them. A `POST /fetch` that returns JSON is a *worse* demonstration of
  the moat than the existing `gnosis URL --warc` one-liner.
- **The refactor that a server "requires" is speculative coupling.** The
  service-layer extraction in the other docs is only *necessary* because they
  want a server. YAGNI says: extract the service layer **when there are two
  callers**, not before. Today there is one caller (the CLI).

---

## 3. What to do NOW (small, offline, server-independent)

### 3.1 Fix the hard-import bug in `llm.py`

`gnosis/integrations/llm.py:11-12` does top-level `import torch` /
`from transformers import ...`. A core `pip install gnosis-markdown` therefore
cannot import the module at all — which is exactly why it has zero tests.
Mirror `integrations/documents.py` (and `run_qmd_integration`, which already
lazy-imports `LLMContextGenerator`): move both imports inside `_load_model()`.

This is not a server prerequisite. It is a correctness bug in shipped code:
the module is unimportable in the default install.

### 3.2 Add hermetic tests for `llm.py` + `qmd.py` (zero coverage today)

Do **not** copy `tests/test_documents.py` — its
`pytestmark = skipif(find_spec("markitdown") is not None, ...)` inverts the
coverage: the positive path is *never* exercised and the negative test *skips*
in the `[docs]`-installed leg. That is the anti-pattern.

Correct pattern: **stub the heavy deps, always run.** No torch, no `qmd`
binary, no HF model download in default CI.

`tests/test_llm_integration.py` (after 3.1 lands, pure helpers need no torch):
- `_aggregate_content`: `sample_files_limit` (only first N), `sample_content_max_chars` + `\n[... truncated ...]`, single-file header stripped, unreadable file skipped, empty dir → `"No content available."`, `> max_files` → `[Note: Showing N of M files]`.
- `_create_messages` → `[{"role":"user","content":…}]`.
- `_clean_thinking_tags`: multiline `<think>…</think>` removed, blank lines collapsed, whitespace stripped.
- `/no_think` appended only when `"qwen"` is in `llm_model.lower()`.
- `generate_context` with `_load_model`/`_generate` monkeypatched: prompt built from `context_prompt_template`, errors wrapped in `RuntimeError("Failed to load LLM model: …")`.
- `cleanup` deletes `model`/`tokenizer` (and `torch.cuda.empty_cache()` when CUDA is mocked present).

`tests/test_qmd_integration.py` (mock `subprocess.run` + `shutil.which`):
- `_verify_qmd_installed` → `QMDNotFoundError` when `shutil.which("qmd") is None`.
- `_run_command` → `QMDCommandError` on non-zero exit, with exit code + stderr in the message.
- `add_collection`: exact argv `["qmd","collection","add",<resolved>,"--name",<name>,"--mask","**/*.md"]`; `"already exists"` branch → parse name → `remove_collection` → retry; retry failure → `QMDCommandError`.
- `_parse_existing_collection_name` regex (`Name:\s+(\S+)`); `None` when absent.
- `add_context`/`embed` argv; `embed(force=True)` appends `-f`; `run_pipeline` order: add_collection → add_context → embed; `collection_exists` True/False.

Real-model smoke test: `@pytest.mark.skipif(not os.getenv("GNOSIS_LLM_SMOKE"))`, never in default CI.

### 3.3 Fix the two bugs that bite the CLI today

- `qmd.py`: add `timeout=` (configurable, sane default) to `subprocess.run` and surface it as `QMDCommandError`.
- `downloader.py`: key the rate limiter **per origin (`netloc`)** instead of one global clock, so `--all` crawls actually honor `concurrent_requests`. Politeness is a property of the target host, not the process.

Both are one-commit fixes with clear tests, and both are prerequisites *if* a
server ever ships — so they're the correct YAGNI investment: do the cheap
shared prerequisite, skip the expensive speculative superstructure.

---

## 4. What to explicitly NOT do now

- Pick a framework (Starlette vs FastAPI) — no caller exists to justify it.
- Build `/fetch`, `/crawl`, `/index/qmd`, `/healthz`, `/metrics` — no demand.
- Build the `gnosis.service` service-layer refactor — one caller today; extract when there are two.
- Build the arq/Redis two-queue model — roadmap already says v2.
- Add `[server]` extra + `gnosis-server` entry point — dead code until a user asks.

---

## 5. Revisit trigger (when server mode *becomes* worth it)

Any one of these makes the server worth building, and not before:

1. A real user/GitHub issue asks for programmatic access (not "would be nice").
2. A second front-end actually needs the pipeline (e.g. an IDE extension or CI action) — then do the service-layer extraction for *that* caller, and the server falls out almost free.
3. Someone volunteers to own auth + caps + observability + on-call for a public endpoint.

Until then: **ship the moat, fix the bugs, test the untested.** An API is not
a feature if the output it wraps is unauditable — and the output is already
auditable from the CLI.
