# Design — SSRF DNS-rebinding TOCTOU: the **network-security** fix

Panel item: **pin-netsec**. Author: netsec panel member. Status: proposal
(implemented in-tree). Cross-refs: `design-ssrf-ip-pinning.md` (pin-dns —
resolution fix), `design-ssrf-ip-pinning-keepalive.md` (pin-pool — pool /
keep-alive dimension). This doc is the security-analysis complement: it states
the *correct* fix and the threat model it closes, and calls out what it does
not cover.

## Verdict

The disclosed limitation is a genuine, exploitable **resolve-then-connect
race**, and the correct fix is **IP pinning at the socket layer** — not a
stronger `assert_public_url`, not a DNS cache, not a second hook. The working
tree now implements this:

- `gnosis/core/network.py` — `PinnedNetworkBackend` (resolve **once**,
  validate **all**, dial the validated IP literals) and `SSRFPinnedTransport`
  (an `httpx.AsyncBaseTransport` that builds an
  `httpcore.AsyncConnectionPool(network_backend=PinnedNetworkBackend(...))`).
- `gnosis/core/downloader.py` + `gnosis/core/robots.py` — both now build their
  clients with `build_transport(allow_private_network=...)`; the old
  validate-then-connect `request` event hooks are **deleted**.

This is a patch-level security fix. It is *not* a fix for the orthogonal
block-list completeness gap (CGNAT `100.64.0.0/10` is not currently classified
as private — see §5), which should ship as its own item.

---

## 1. Root cause

Two independent DNS resolutions, two independent trust decisions, separated in
time:

1. `assert_public_url()` → `loop.getaddrinfo(host, port)` (**resolution #1**)
   → validates → returns.
2. `httpx`/`httpcore` → `AnyIOBackend.connect_tcp()` →
   `anyio.connect_tcp(remote_host=host, ...)` (**resolution #2**) → dials
   whatever *that* returns, unvalidated.

An attacker who controls the authoritative resolver answers #1 with a public
address (guard passes) and #2 with `169.254.169.254` / `127.0.0.1` / RFC1918
(the transport connects). The `request` event hook re-entered
`assert_public_url` on every hop, but it ran *before* resolution #2 and could
not constrain which IP the transport ultimately dialed. "Make the guard
stricter" cannot fix this: the connect step still resolves independently.

The fix collapses #1 and #2 into a single resolution performed at connect
time, and forces the dial onto the validated set.

## 2. The correct fix

The only seam httpcore exposes to control *where* a socket dials is the
network backend: `AsyncConnectionPool(network_backend=...)`. httpx's stock
`AsyncHTTPTransport` does not thread that through, so the transport must be
provided. The tree uses a standalone `httpx.AsyncBaseTransport`
(`SSRFPinnedTransport`) that mirrors httpx's own `handle_async_request`
byte-for-byte (same `httpcore.Request` shape, same `AsyncResponseStream` wrap,
same exception mapping), differing only in the pool's backend.

`PinnedNetworkBackend.connect_tcp(host, port, ...)`:

1. **IP literal** → validate the literal, block or dial directly (no DNS, no
   rebinding surface).
2. **Hostname** → `loop.getaddrinfo` **once**; if *any* returned address is
   private/reserved → `PrivateNetworkBlocked` (fail closed against a resolver
   that mixes public + private to win a race); otherwise dial the validated
   **IP literals** in order (sequential fallback under one overall connect
   deadline — no timeout multiplication on dual-stack hosts).
3. `connect_unix_socket` → fail closed (a UDS bypasses TCP/IP addressing).

Because the backend is consulted for **every** new TCP connection, every
redirect hop and every distinct origin is re-resolved + re-validated + re-pinned.
A socket is pinned once at dial time and re-validated only when a new socket is
opened — never on keep-alive reuse, never from a stale cache.

### Why pinning is safe for TLS

`httpcore`'s connection layer does `stream.start_tls(server_hostname=origin.host)`
*after* `connect_tcp`, using the **hostname** for SNI and certificate
verification — independent of the IP the backend dialed. Pinning therefore does
not weaken certificate verification, does not break SNI, and does not break
virtual hosting. (Verified against httpcore 1.0.9 / httpx 0.28.1 in-tree.)

### Why keep-alive survives

The pin lives at the *socket* layer; the pool key, `Host` header, and TLS SNI
all remain the hostname. Pool reuse skips DNS entirely (correct — no
re-resolution without re-validation); reconnect re-resolves (correct — fresh
validation). The pin-pool doc (`design-ssrf-ip-pinning-keepalive.md`) confirms
this structurally and I endorse it.

## 3. Threat model

**Closed**
- DNS rebinding against direct connections (the disclosed race): the validated
  address is the dialed address; there is no second resolution to win.
- Redirect-hop rebinding: each hop is a new connection, hence a new pinned
  resolve.
- Mixed public/private answer sets: any-private → block.
- IPv4-mapped IPv6 (`::ffff:a.b.c.d`), loopback, RFC1918, link-local,
  multicast, reserved, unspecified: unchanged block-list, now enforced at the
  dial.

**Not covered (fail closed or out of scope)**
- **HTTP/HTTPS/SOCKS proxies**: a proxy moves DNS resolution off-box; client-side
  pinning cannot enforce the *target* address. gnosis configures no proxy, and
  `SSRFPinnedTransport` does not implement a proxy path — unsupported while the
  guard is on.
- **Unix domain sockets**: bypass TCP/IP; `connect_unix_socket` fails closed.
- **CGNAT `100.64.0.0/10`** and any other block-list gaps: independent of the
  rebinding race (see §5). Not addressed here.
- **Render sidecar**: `--render` hands the URL to an external browser process;
  its SSRF surface is outside this transport's boundary (unchanged, opt-in).

## 4. Acceptance criteria

- `AC-1` A hostname is resolved at most once per TCP connection (no second,
  racy resolution). *Test:* `test_resolves_once_and_pins_to_validated_ip`.
- `AC-2` The dialed address is one of the validated IPs, never a fresh
  resolution. *Test:* same test asserts `dialed == [validated_ip]`.
- `AC-3` Any private address in the answer set blocks the connection.
  *Test:* `test_blocks_if_any_resolved_address_is_private`.
- `AC-4` Private IP literals and private hostnames (`localhost`) block without
  dialing. *Tests:* `test_blocks_private_ip_literal`,
  `test_blocks_private_hostname`.
- `AC-5` Sequential fallback does not multiply the connect timeout.
  *Test:* `test_sequential_fallback_budgets_timeout_across_candidates`.
- `AC-6` `--allow-private-network` bypasses the guard with zero behavior change
  (stock transport). *Tests:* `test_allow_private_network_skips_validation`,
  `test_build_transport_returns_none_when_allowed`,
  `test_downloader_allows_private_when_opted_in`.
- `AC-7` The full downloader path blocks a private fetch end-to-end, and the
  downloader + robots clients actually install the pinned transport.
  *Tests:* `test_downloader_blocks_private_by_default`,
  `test_downloader_uses_pinned_transport`, `test_transport_blocks_private_literal`.

*Test command:* `.venv/bin/python -m pytest tests/test_network.py -q` → 31 passed.

## 5. Out of scope (flagged, not fixed here)

- **CGNAT `100.64.0.0/10`**: `ipaddress.is_private` is `False` for this range
  (and `is_reserved` does not catch it), so `100.64.0.0/10` currently bypasses
  the block-list. This is a *classification* gap, orthogonal to the rebinding
  race, and deserves its own item (add an explicit shared-space check to
  `_is_private_address`). The pin-dns doc flags the same gap.
- **In-flight resolution dedup** for a concurrent burst to one origin (each
  connect re-resolves; correct but redundant). Safe to add as a per-origin
  in-flight join — never a persistent cache (would reopen the rebinding
  surface). Nice-to-have.
- **End-to-end redirect-to-private SSRF test**: still not hermetically
  simulatable (public → private hop). Documented in `SECURITY.md`; the redirect
  path is covered at the backend level (per-hop re-resolve) plus unit tests.

## 6. Implementation notes

- `PinnedNetworkBackend` subclasses `httpcore._backends.anyio.AnyIOBackend` so
  socket creation (timeout, TCP_NODELAY, socket options, exception mapping) is
  httpcore's own; only the resolution step is overridden.
- `SSRFPinnedTransport` imports `httpx._config.create_ssl_context` /
  `DEFAULT_LIMITS` and `httpx._transports.default.AsyncResponseStream` /
  `map_httpcore_exceptions` — private but stable httpx internals, the same ones
  httpx's stock transport uses. A regression test asserting these imports
  (or an httpx version pin) is worth adding if httpx is upgraded.
- `build_transport()` returns `None` (stock transport) when the guard is opted
  out, so `--allow-private-network` is exactly the pre-fix behavior.
