# Design note — HTTP server / API mode (auth, rate-limiting, SSRF) + qmd/llm test coverage

> Panel review: `api-sec`. Author: design panel (security/API persona).
> Status: recommendation — no API exists today; this scopes the work and the
> non-negotiable security gates before any server code lands.

## 1. Current state (what the review found)

- **No HTTP server / API mode exists.** `gnosis` is CLI-only (`gnosis`,
  `gnosis-bench`, `gnosis-doc`). `ROADMAP.md` explicitly defers "distributed
  queue/webhooks/cluster" to v2. Nothing in `gnosis/` binds a socket.
- **The SSRF guard is the strongest part of the codebase** and transfers
  cleanly to an API *only if* the API forces it on. `PinnedNetworkBackend`
  resolves once, validates every returned address, and pins the dial to a
  validated IP — DNS-rebinding TOCTOU is closed, redirects go through the same
  pinned pool (`follow_redirects=True` on an `httpx.AsyncClient` using
  `SSRFPinnedTransport`).
- **The optional llm/qmd integrations have zero test coverage.** There is no
  `tests/test_qmd.py` and no `tests/test_integrations_llm.py`. The `[qmd]`
  extra (`torch`, `transformers`) is not installed in CI (only `.[test]`), so
  `131 passed` proves nothing about those modules. `gnosis/integrations/qmd.py`
  and `gnosis/integrations/llm.py` are shipped-but-untested.
- **The downloader has no response-size cap** (`raw_bytes=response.content`
  and `html=response.text` read the whole body into memory), and
  `rate_limit_ms` is a *global* outbound throttle across one `Downloader`
  instance — a politeness knob, not an inbound-API limiter.

## 2. Verdict (opinionated)

Ship the API as an **optional extra (`gnosis-markdown[api]`)** behind the same
lazy-import seam the project already uses for `docs`/`qmd`. Make it **auth-required
and SSRF-forced, never opt-out**, and gate the expensive integrations
(`--qmd-index`, `--render`) **off by default** and **not client-controllable**.
Do not add the API to core deps; it would drag the pure-MIT runtime toward a web
framework and enlarge the CVE blast radius for a CLI that is deliberately static.

Framework choice: **FastAPI + uvicorn** (or plain Starlette). Rationale: the API
is fundamentally about validating untrusted request bodies (pydantic), returning
structured JSON, and declaring auth/rate-limit dependencies — exactly the
things you do *not* want to hand-roll on `http.server`. ASGI also makes the
whole thing testable in-process with `httpx.ASGITransport`/`TestClient` without
opening ports.

## 3. Non-negotiable security gates

### 3.1 The trust boundary inverts — threat model changes

CLI = trusted operator, self-inflicted risk, inputs under your control.
API = untrusted remote callers controlling `url`, `--all`, `--warc`,
`--chunk`, `--qmd-index`, `--render`, headers, auth to *target* sites. Every
"operator choice" becomes an attacker-controlled dial. Treat the API as an
**open proxy / SSRF oracle / amplification engine** and design for that.

### 3.2 Auth — required, constant-time, fail-closed

- Reject requests **before** any fetch. No unauthenticated mode, no
  `--no-auth` server flag.
- One static bearer key from the environment (`GNOSIS_API_TOKEN`) is the
  minimum; compare with `hmac.compare_digest` (constant time) against a
  per-request secret, never `==`. Fail closed (503/401) if the env var is unset.
- **Prefer scoped tokens** (read/scrape vs. crawl vs. admin) even if v1 ships
  one key. A single shared secret on a scraping API becomes a leaked-key →
  free-proxy incident.
- Do not reuse the *target-site* auth (`downloader.auth`, `--bearer-token-env`)
  as the *API* auth. They are different layers; keep them separate.

### 3.3 SSRF — the guard survives, but the API adds new surface

What already holds (verify by tests, don't trust by argument):
- Redirect-to-private is blocked per hop (pinned pool on every redirect).
- DNS rebinding is blocked (resolve-once, validate-all, pin).
- IP obfuscation classes (decimal/octal/hex, IPv4-mapped IPv6) are blocked at
  the *resolved-address* validation stage — add explicit tests for
  `http://2130706433/`, `http://0x7f000001/`, `http://127.1/`,
  `http://[::ffff:127.0.0.1]/` to lock it.

What is **new** in API mode:
1. **`allow_private_network` must be hard-disabled** for API requests. The
   client must never be able to set it (no field, no header, no config
   override). The bypass flag existing in the shared `DownloaderSettings` is
   the #1 way this becomes an internal-network scanner.
2. **Bind address default = `127.0.0.1`.** Never `0.0.0.0` without an explicit
   `--host` flag + warning. An API that is both unauthenticated and
   `0.0.0.0`-bound is a self-pwn.
3. **Error-oracle suppression.** `PrivateNetworkBlocked`'s message leaks
   `host -> resolved-ip` (see `network._block`). In CLI that's fine; in API it
   is a timing/oracle signal for internal mapping. Return a generic `403` with
   a stable body ("target blocked by SSRF policy"), log the detail server-side.
4. **Non-HTTP egress not under the guard.** The model download in
   `integrations/llm.py` (`AutoTokenizer/AutoModelForCausalLM.from_pretrained`)
   uses `huggingface_hub`'s own HTTP stack, **not** `SSRFPinnedTransport`. If
   the API ever lets a caller influence `llm_model` (or `qmd` runs at all),
   that is unguarded egress + unbounded download. Do not expose `llm_model` or
   any `qmd.*` setting via the API; keep them server-side config only.
5. **Open-proxy / abuse is the real SSRF-adjacent risk.** Even with private
   nets blocked, an attacker gets a free, rate-limited-in-name-only fetcher to
   hit arbitrary public targets, launder traffic, or hammer a victim site.
   Mitigate with §3.4 + per-target politeness (the existing robots/crawl-delay
   path) + an allowlist/denylist of host suffixes as a server policy layer.

### 3.4 Rate limiting — two distinct axes (this is the part most designs get wrong)

- **Inbound (protect *you*):** per-API-key token bucket / sliding window, plus
  a **global concurrency semaphore** bounding simultaneous fetches. Without the
  semaphore, `crawler.concurrent_requests=5` only bounds *one* crawl; N clients
  × crawl = unbounded outbound fan-out. Return `429` with `Retry-After`.
- **Outbound (protect *targets*):** the existing `rate_limit_ms` is a single
  global clock on one `Downloader`; for an API serving many callers it becomes
  a global bottleneck AND is bypassed by creating fresh `Downloader`s. Rate-limit
  **per target domain** (extend `RobotsChecker.crawl_delay` into a per-origin
  token bucket) and keep a modest global outbound ceiling.
- **Quota on the expensive integrations:** `--qmd-index` triggers a model load
  + embedding + subprocess spawn; `--render` spawns a browser. These are
  CPU/wallet DoS vectors. Default **off**; if enabled, require a distinct scoped
  token and cap concurrent expensive jobs (ideally a single-worker queue).

### 3.5 Resource exhaustion (the CLI never had to care)

- **Response-size cap** (new, mandatory): `raw_bytes=response.content` loads the
  entire body. An API that fetches arbitrary URLs is a memory-DoS vector. Stream
  to the WARC/content-addressed store with a `max_response_bytes` limit and
  `413` on overflow.
- **Per-request wall-clock budget** across retries/redirects (the downloader's
  retry backoff `2**attempt` × `timeout` is unbounded for a hostile slow-loris
  target).
- **`subprocess.run` has no timeout** in `integrations/qmd.py`. In API mode a
  hung `qmd embed` = a hung worker. Add `timeout=` + kill.
- **Synchronous CPU-bound work blocks the loop:** `LLMContextGenerator` loads
  and runs a model inline (and `run_qmd_integration` is invoked synchronously
  at the end of `download_and_convert`). In an API it must run in a worker
  thread/process, not the event loop.

## 4. Proposed surface (concrete)

```
POST /v1/scrape   {url, options{...}} -> 200 {markdown, frontmatter, content_hash, bytes_sha256}
POST /v1/crawl    {url, options{...}} -> 202 {job_id}   (bounded job queue)
GET  /v1/jobs/{id}                     -> 200/202/4xx
GET  /healthz                          -> 200 (no auth, no info leak)
```

- `options` is a strict, allowlisted subset of `Settings` — never the raw
  `Settings` dataclass (it contains `allow_private_network`, auth, `qmd.*`,
  `render.*`, which must not be client-settable).
- Response JSON carries the same provenance fields as the frontmatter
  (`bytes_sha256`, `content_hash`, `fetched_at`, `redirect_chain`) — provenance
  is the moat, so the API must not strip it.
- Errors are machine-readable JSON (`{"error": {"code": "ssrf_blocked",
  "retryable": false}}`), never stack traces, never internal IPs.

## 5. Test coverage for the optional llm/qmd integrations (the named gap)

Two hard rules:
1. **No `torch`/`transformers` in CI.** Test `integrations/llm.py` by mocking
   at the module-import boundary (or injecting a fake model/tokenizer into
   `_load_model`), never by downloading a real model.
2. **No `qmd` binary in CI.** Test `integrations/qmd.py` by mocking
   `subprocess.run` / `shutil.which`; assert argv construction, never spawn
   `qmd`.

Concrete cases:
- `qmd.py` (unit, mocked subprocess):
  - `_verify_qmd_installed` → `QMDNotFoundError` when `shutil.which` is `None`.
  - `add_collection` happy path argv; `"already exists"` branch → `remove` +
    retry argv (and the retry-fails → `QMDCommandError` path).
  - `_parse_existing_collection_name` against *real* QMD output fixtures
    (the `Name:\s+(\S+)` regex is brittle — pin it with fixtures now).
  - `_run_command` maps nonzero exit → `QMDCommandError` with stderr; add a
    `timeout` case.
  - **injection check:** `collection_name` and `description` are passed as list
    argv (no shell) — assert a hostile name (`http://evil.com/$(id)`) is not
    interpreted.
- `llm.py` (unit, no model):
  - `_aggregate_content`: truncation at `sample_content_max_chars`, `sample_files_limit`
    cap, single-file header removal, unreadable-file skip.
  - `_clean_thinking_tags` on `<think>` multi-line / whitespace fixtures.
  - `_create_messages` and prompt assembly; **`/no_think` suffix only for
    `qwen`** model names.
  - `generate_context` with a stubbed model/tokenizer: verifies prompt input,
    returns stripped output, and maps load/generate failures → `RuntimeError`.
- Wiring (`run_qmd_integration` in `cli/main.py`):
  - `settings.qmd.enabled == False` → no-op (fast guard, prevents accidental
    heavy path).
  - `QMDIntegrator()` raising `QMDNotFoundError` → warning + graceful skip.
  - `LLMContextGenerator.generate_context` raising → warning + skip, no crash.
- API (ASGI in-process, mocked `Downloader`):
  - 401 on missing/wrong token; constant-time compare.
  - 429 after rate-limit exhaustion; `Retry-After` present.
  - 403 on private literal/hostname/redirect-to-private/obfuscated-IP URLs.
  - 413 on oversize response; timeout path; job queue concurrency cap.
  - `allow_private_network`/`qmd`/`render` not settable via request.

## 6. Concrete defects to fix before or with the API (regardless of API)

1. `network._block` leaks `host -> ip` into the exception message → separate
   "public exception" from "logged detail".
2. `integrations/qmd.py::_run_command` — no `subprocess.run(timeout=)`.
3. `integrations/llm.py::_load_model` — model download bypasses the SSRF-guarded
   transport and has no size/rate control.
4. `integrations/llm.py::_generate` — `do_sample=True` always; a `temperature=0`
   setting cannot request deterministic decoding.
5. `llm.py::_aggregate_content` feeds raw `.md` including the YAML provenance
   frontmatter into the LLM prompt (noise; should reuse `_read_md_body`).
6. `Downloader.fetch_result` holds both `html` (str) and `raw_bytes` (bytes) —
   ~2× body memory, no cap. Stream + cap in API mode.
