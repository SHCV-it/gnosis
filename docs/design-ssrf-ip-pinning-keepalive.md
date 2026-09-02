# Design — SSRF IP pinning: **connection reuse / keep-alive**

Panel item: **pin-pool**. Author: SSRF panel member (connection-pool dimension).
Status: proposal. Cross-ref: `design-ssrf-ip-pinning.md` (the "pin-dns" item
covers the *resolution* fix; this doc covers the *pool* it must not break).

## Verdict

The IP-pinning implementation in the working tree
(`PinnedNetworkBackend` + `SSRFPinnedTransport`) **does preserve HTTP
keep-alive, and it does so for a structural reason, not by luck**: the pin
lives at the *socket* layer while the pool key, the `Host` header, and TLS
SNI all remain the *hostname*. I endorse the architecture. But there is one
real connection-setup regression (F1) and one broken test (F2) that must be
fixed before this ships, plus two keep-alive knobs being silently dropped
(F3) that should be fixed now.

Do **not** solve any of this by keying the pool on the IP. That would collapse
distinct virtual hosts onto one bucket, break TLS cert verification, and let an
attacker co-opt a keep-alive slot via a colliding IP. The hostname key is the
whole point.

---

## 1. Why pinning preserves keep-alive (the two-layer split)

The design works because httpcore separates *who we talk to* (the origin,
hostname) from *where the socket goes* (the network backend). Verified against
the installed copies — `httpcore 1.0.9`, `httpx 0.28.1`:

**Layer 1 — pool key = hostname.** `AsyncConnectionPool._assign_requests_to_connections`
does `origin = pool_request.request.url.origin` and assigns a connection iff
`connection.can_handle_request(origin)`, which is literally
`origin == self._origin` (`httpcore/_async/connection.py`). So a connection is
keyed by `scheme://host:port` — never by the IP the backend dialed.

**Layer 2 — socket pin = IP, invisible to the pool.** `AsyncHTTPConnection._connect`
calls `backend.connect_tcp(host=self._origin.host, ...)` and, for HTTPS, then
`stream.start_tls(server_hostname=sni_hostname or self._origin.host, ...)`.
Our backend resolves the hostname internally and dials validated **IP
literals**, so httpcore never learns the IP. Result: the pool still stores the
connection under the hostname, and TLS still verifies the **hostname**.

**Layer 3 — response wrapping is byte-for-byte the stock path.**
`SSRFPinnedTransport.handle_async_request` is a faithful mirror of httpx's own
`AsyncHTTPTransport.handle_async_request` (same `httpcore.Request` shape, same
`AsyncResponseStream` wrap). So when the downloader reads `response.content`
(`Response.read` → `iter_bytes`, which exhausts the httpcore stream), the
connection is returned to the idle pool exactly as with the default transport.

Net keep-alive lifecycle with pinning:

```
req#1 GET https://a.example/x
  pool empty -> connect_tcp("a.example", 443)
    backend: getaddrinfo ONCE -> validate ALL -> dial IP_A   (1 DNS lookup)
  response read -> connection idle, keyed "a.example"
req#2 GET https://a.example/y
  pool finds idle conn, origin "a.example" -> REUSE           (0 DNS lookups)
  same socket, still pinned to IP_A; Host + SNI still "a.example"
... keep-alive expires / server closes ...
req#N -> connect_tcp again -> fresh getaddrinfo -> re-validate -> maybe IP_B
```

The security property is exactly the reuse property: **a socket is pinned once
at dial time and re-validated only when a new socket is opened — never on
reuse, and never from a stale cache.** Reuse skips DNS (good), reconnect
re-resolves (good, fresh validation), and there is no path that re-resolves
without re-validating.

---

## 2. Findings (ranked)

**F1 — sequential fallback applies the full timeout per candidate (must fix).**
`connect_tcp` loops `for ip in candidates: super().connect_tcp(ip, timeout=...)`
passing the **same full `timeout`** to every attempt. A dual-stack host whose
first candidate is unreachable (dead IPv6, common) takes up to
`len(candidates) × timeout` to fail, versus anyio's happy-eyeballs which races
the family set. This is not a keep-alive break, but it is a connection-setup
latency regression the pin-dns doc already flagged. Fix by budgeting the
deadline across candidates (below) — or race-all/first-wins/then-cancel.

**F2 — `tests/test_network.py::test_ssrf_guard_hook_blocks_private` now fails
(must fix).** The implementation removed `Downloader._ssrf_guard` (correctly —
it was the validate-then-connect hook being deleted), but the test still calls
it and dies with `AttributeError`. Confirmed by running
`.venv/bin/python -m pytest tests/test_network.py -q` → 1 failed, 18 passed.
Rewrite the test to assert the *new* boundary (a pinned fetch to a private IP
literal raises; see AC-POOL-6).

**F3 — keep-alive knobs silently dropped (should fix).** `build_transport()`
returns `SSRFPinnedTransport()` with hardcoded `DEFAULT_LIMITS`, `http2=False`,
and never threads `limits` / `http2` / `retries` / `local_address` /
`socket_options`. Today gnosis exposes none of these (no settings for them), so
there is no live bug — but the moment anyone wants `http2` or a custom
`max_keepalive_connections`, the pinning transport silently ignores it. Thread
them through now so the keep-alive contract stays honest.

**F4 — `local_address` family mismatch (minor).** If a `local_address` is
IPv4-only and the first pinned candidate is IPv6 (or vice versa), the first
dial fails and we retry the next candidate. Self-healing but wasteful; order
candidates by the `local_address` family when one is set.

**F5 — 4xx/5xx bodies not consumed → connection not returned (pre-existing,
out of scope).** `fetch_result` calls `raise_for_status()` *before* reading the
body, so on 404/403 the response stream is never exhausted and the connection
is not returned to the pool. Not caused by pinning, but a crawler sees many
4xx and this quietly eats keep-alive capacity. Optional follow-up: read/`aclose()`
the response before raising.

**F6 — burst re-resolution (no change required, note only).** Each new TCP
connection costs one `getaddrinfo`. On the first concurrent burst to one host
(crawler default `concurrent_requests=5`, pool `max_connections` default 100),
that can mean several identical resolutions for the same origin. This is
*correct* — each is resolve→validate→dial atomic — just redundant. Do **not**
add a persistent pin cache (reopens the rebinding surface; agree with the
pin-dns doc). A per-origin *in-flight* dedup (share one in-flight `getaddrinfo`
among simultaneous connects to the same origin) is safe because the answer is
only ever used inside that single connect window. Nice-to-have.

---

## 3. Recommended code changes

**3a. Deadline-budgeted fallback (fixes F1).**

```python
# in PinnedNetworkBackend.connect_tcp, after building `candidates`:
loop = asyncio.get_running_loop()
deadline = None if timeout is None else loop.time() + timeout
last_error = None
for ip in candidates:
    remaining = None
    if deadline is not None:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
    try:
        return await super().connect_tcp(ip, port, remaining,
                                         local_address, socket_options)
    except (ConnectError, ConnectTimeout) as exc:
        last_error = exc
        continue
raise ConnectError(f"failed to connect to {host}: {last_error}")
```

(For a true happy-eyeballs replacement, race all candidates with a short
stagger and cancel losers — but the budgeted loop is the minimal correct fix.)

**3b. Thread keep-alive knobs through the transport (fixes F3).**

```python
def build_transport(allow_private_network: bool, *,
                    limits: httpx.Limits | None = None,
                    http2: bool = False, retries: int = 0,
                    local_address: str | None = None,
                    socket_options=None) -> httpx.AsyncBaseTransport | None:
    if allow_private_network:
        return None
    return SSRFPinnedTransport(limits=limits, http2=http2, retries=retries,
                               local_address=local_address,
                               socket_options=socket_options)
```

**3c. Fix the test (fixes F2).** Replace the `_ssrf_guard` test with a
pinned-fetch assertion (private literal raises through the transport), and add
the keep-alive acceptance tests in §4.

---

## 4. Acceptance criteria (keep-alive specific — the pin-pool contract)

Hermetic: a local `asyncio` test server counts `accept()`s and (for the
resolution-count assertions) the loop's `getaddrinfo` is monkeypatched with a
counter.

- **AC-POOL-1 (reuse).** Two sequential fetches to the same origin open
  **one** TCP connection (server `accept()` count == 1) and `getaddrinfo` is
  called **exactly once** across both.
- **AC-POOL-2 (fresh validation on reconnect).** After the server force-closes
  the connection, the next fetch re-resolves (counter increments) and
  re-validates — reuse must never skip validation, reconnect must never reuse
  a stale pin.
- **AC-POOL-3 (pin stability across reuse).** Resolver returns `[IP_A, IP_B]`;
  first connect lands on `IP_A`; the reused connection still peers at `IP_A`
  (no mid-stream re-pin on a reused socket).
- **AC-POOL-4 (timeout budget).** A host whose first pinned candidate is
  unreachable falls back within ~1×`timeout`, not `N×timeout`.
- **AC-POOL-5 (TLS/SNI intact).** An https fetch to a *hostname* still
  verifies the cert against the hostname — pinning must never set
  `server_hostname` to the dialed IP.
- **AC-POOL-6 (boundary + redirects).** A fetch to a private IP literal raises
  `PrivateNetworkBlocked` (new test replacing the dead `_ssrf_guard` test);
  a redirect to the same origin reuses the connection, a redirect to a new
  origin gets its own pinned connect + validation.

---

## 5. Residual risk (honest)

- The pool key is the hostname, so an attacker who can *make us reuse a
  connection we already validated* cannot affect the pin (it stays on the
  validated IP). The remaining trust boundary is unchanged from pin-dns: we
  validate the **address**, not the **route**, and we trust the recursive
  resolver's *answers* only insofar as we pin and re-validate them per socket.
- If `http2` is ever enabled, httpcore's origin equality (`can_handle_request`)
  already rules out cross-host coalescing by IP, so the hostname-keyed pool
  remains correct under h2.
