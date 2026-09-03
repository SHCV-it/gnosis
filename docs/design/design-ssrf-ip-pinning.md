# Design — SSRF DNS-rebinding TOCTOU: **IP pinning**

Panel item: **pin-dns**. Author: SSRF panel member. Status: proposal.
Scope: `gnosis/core/network.py`, `gnosis/core/downloader.py` (plus a new
`gnosis/core/transport.py`). The other SSRF items (redirect hop enforcement,
CGNAT classification, proxy trust) are touched only where they interact with
pinning.

## Verdict

The disclosed limitation is real and **fixable for the price of ~80 lines**,
and it is *not* fixable by making `assert_public_url` stricter. The guard and
the transport resolve the hostname **twice, at different times**; any
"resolve-then-validate-then-connect" scheme that leaves the connect step to
re-resolve will keep the race. The fix is to **move resolution + validation
into the transport's TCP connect step and pin the socket to the validated
addresses**, so there is exactly **one** DNS resolution per connection and the
bytes go to an address we checked.

My recommendation: **ship it as a patch-level security fix**, with the
allow-list hardening folded in, because the current block-list has a live
bypass (CGNAT `100.64.0.0/10` — see §4) that is independent of the rebinding
race.

---

## 1. Root cause (exactly where the race is)

Two independent resolutions, two independent trust decisions:

1. `network.assert_public_url()` calls `loop.getaddrinfo(host, port)` —
   **resolution #1** — validates the results, returns.
2. `httpx.AsyncClient` → `httpcore.AsyncConnectionPool` → `AnyIOBackend.connect_tcp()`
   calls `anyio.connect_tcp(remote_host=host, ...)` — **resolution #2** — and
   connects to whatever *that* returns. (`httpcore/__init__.py` 1.0.9,
   `_backends/anyio.py::connect_tcp`; confirmed against the installed copy.)

An attacker-controlled resolver answers #1 with a public address (guard passes)
and #2 with `169.254.169.254` / `127.0.0.1` / RFC1918 (transport connects).
That is the TOCTOU. The request event hook `Downloader._ssrf_guard` and the
`RobotsChecker._guard` both re-enter `assert_public_url`, but they can only
*widen* blocking — they run *before* resolution #2 and cannot constrain which
IP the transport ultimately dials.

Pinning closes it by making #1 and #2 the **same** resolution, performed at
connect time, with the dial forced onto the validated set.

## 2. The fix: a pinned network backend

Inject at the only seam httpcore exposes: `AsyncConnectionPool(network_backend=...)`.
httpx's `AsyncHTTPTransport` hard-codes the pool construction, but
`handle_async_request` uses **only** `self._pool`, so we subclass and swap the
pool. No fork of httpx/httpcore needed.

New module `gnosis/core/transport.py` (or fold into `network.py`):

```python
import httpcore, httpx
from httpx._transports.default import AsyncHTTPTransport

class PinnedTransport(AsyncHTTPTransport):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)          # builds ssl_context, proxy config
        # super() also set self._pool; replace it with a pinned one for the
        # direct-connection path (no proxy).
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=self._pool._ssl_context,
            max_connections=..., keepalive_expiry=...,
            network_backend=PinnedNetworkBackend(),
        )
```

`PinnedNetworkBackend(httpcore.AnyIOBackend)` overrides `connect_tcp`:

```python
async def connect_tcp(self, host, port, timeout=None,
                      local_address=None, socket_options=None):
    addrs = await resolve_public_addresses(host, port)  # single resolution
    if not addrs:
        raise httpcore.ConnectError(f"no public address for {host}")
    # happy-eyeballs across the PINNED set; never pass `host` back to anyio
    return await _connect_first(addrs, port, timeout, local_address, socket_options)
```

The critical rule: **`anyio.connect_tcp`/`loop.create_connection` must receive
only IP literals from `addrs`, never the hostname.** An IP literal does not
trigger DNS, so the second-resolution window disappears.

`resolve_public_addresses(host, port)`:

```python
infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
seen, out = set(), []
for _f, _t, _p, _c, sockaddr in infos:
    ip = sockaddr[0]
    if ip in seen:
        continue
    seen.add(ip)
    addr = ipaddress.ip_address(ip)
    if _is_private_address(addr):            # allow-list, see §4
        raise PrivateNetworkBlocked(f"{host} -> {ip}")
    out.append((_f, ip))                      # family kept for v6/v4 ordering
return out
```

**Fail closed on mixed sets**: if *any* returned address is private, raise —
do not connect to the public subset. A mixed answer is the attacker's bread
and butter.

Wire-up in `Downloader._get_client`:

```python
transport = None if self.settings.allow_private_network else PinnedTransport(...)
self._client = httpx.AsyncClient(transport=transport, follow_redirects=True, ...)
```

Keep the `request` event hook (`_ssrf_guard`) as a *fail-fast pre-flight* for
IP-literal URLs and for a human-readable error before any dial. It is now
**defense-in-depth, not the enforcement boundary** — the backend re-validates
its own resolution, so a hook that passes can never weaken security.

## 3. Edge cases (each one is a contract, not a footnote)

**Multiple A / AAAA.** Resolve **all** families in one `getaddrinfo` call, dedupe
by IP, validate **every** entry, pin the **entire** validated set. Reject the
whole host if any entry is private. `getaddrinfo(..., type=SOCK_STREAM)` without
a family filter returns both v4 and v6; keep the `family` so the dial can order
them.

**CNAME.** `getaddrinfo` already follows the chain; the only thing we must not
do is *walk the CNAME chain ourselves and re-resolve the intermediate names* —
that reopens the race. Pinning the **final** A/AAAA set is sufficient: we
connect to IPs, never to names, so a CNAME target whose *name* is private is
irrelevant; a CNAME target whose *resolved IP* is private is caught by the
final-set allow-list.

**TTL.** After the single resolution we hold the validated IP for the life of
the connection attempt. TTL expiry does not cause a re-resolve mid-connection;
a later rebind only takes effect on the *next* connection, which re-resolves and
re-validates. Do **not** add a persistent pinned-DNS cache: a stale-but-public
pin is a liveness bug, and a cache that outlives validation is a new attack
surface. HTTP keep-alive reuse of an already-validated TCP socket is safe and
does not re-resolve.

**Happy eyeballs.** The default path's happy-eyeballs lives inside
`anyio.connect_tcp` and *is* the second-resolution bug. We must therefore
implement the v6/v4 fallback ourselves over the pinned set: order `addrs`
(IPv6 first per RFC 6724 intent), start connect attempts, and return the first
success — a 300 ms stagger for the v4 attempt is a nice-to-have; a
"race all, first wins, cancel the rest" is acceptable and simpler. Honor
httpcore's `timeout` (`anyio.fail_after(timeout)`), `local_address`, and
`socket_options` (re-apply; anyio sets `TCP_NODELAY` for asyncio by default).

**IPv4-mapped / 6to4 / Teredo.** Unwrap `ipv4_mapped` before classification
(already done). Fold in `6to4` (`2002::/16`) and `Teredo` (`2001::/32`) — both
are tunnels into private space and are **not** `is_global`. The allow-list in
§4 handles them structurally.

**Redirects.** `follow_redirects=True` re-enters the pool per hop, so every hop
gets its own pinned connect. The per-hop hook still fires (httpx runs request
hooks on each redirect), giving fail-fast + clear errors; the backend is the
authoritative gate on every hop.

**Proxy.** `httpx.AsyncClient(trust_env=True)` (the default) honors
`HTTP(S)_PROXY`. With a proxy the pinned backend is bypassed — the proxy does
the resolution and the dial, and the proxy itself is an SSRF primitive. This is
a separate item; for pinning I recommend **at minimum** setting `trust_env=False`
for the guarded client (or resolving/validating the proxy address and pinning
*that* connection). Flag, don't silently leave it.

## 4. Fold in: allow-list instead of block-list

The current `_is_private_address` is a block-list. It has a live bypass
(verified on this repo's Python 3.12.13):

| Address | `is_private` | `is_global` | currently blocked? |
| --- | --- | --- | --- |
| `100.64.0.1` (CGNAT shared space) | False | False | **NO** ← bypass |
| `198.18.0.1` / `192.0.2.1` / `203.0.113.1` | True | False | yes |
| `169.254.169.254` | True | False | yes |
| `8.8.8.8` | False | True | allowed |

A scraper only ever needs to reach the public internet, so the classifier should
be an **allow-list**: after unwrapping mapped addresses, block `not
addr.is_global`. Keep the individual category checks only to produce
human-readable error strings. This single change also closes CGNAT, 6to4,
Teredo, and any future special-use prefix that Python already models.

```python
def _is_private_address(addr):
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return not addr.is_global
```

## 5. Acceptance criteria (testable)

1. `resolve_public_addresses("dual.example", 80)` where getaddrinfo returns
   `[public, 10.0.0.1]` → raises `PrivateNetworkBlocked` (mixed set, fail closed).
2. `resolve_public_addresses` on `100.64.0.1` → raises (CGNAT gap closed).
3. **Single-resolution invariant**: monkeypatch the loop's `getaddrinfo` with a
   counter; a `PinnedNetworkBackend.connect_tcp` to a hostname calls it **once**
   (proves the dial is pinned and no second lookup happens). Contrast with the
   current path, which calls it twice.
4. **Rebinding simulation**: a fake resolver returns public on call 1 and
   private on call 2; the pinned downloader never dials private (connect
   attempts are observed to be IP literals from call 1 only).
5. Happy-eyeballs set is fully validated: a host resolving to `[2001:db8::1,
   8.8.8.8]` raises (v6 ULA/documentation address is not global).
6. `allow_private_network=True` still uses the default transport and reaches
   `127.0.0.1` (existing tests must keep passing).
7. Existing `tests/test_network.py` and `tests/test_downloader.py` stay green;
   the `_ssrf_guard` hook unit test keeps passing unchanged.

Hermetic note: with pinning, the "no end-to-end redirect-to-private test"
limitation in `SECURITY.md` can finally be lifted *in part* — a unit test can
drive a fake resolver and assert the backend raises, without needing a real
public→private route in CI.

## 6. Residual risk (honest)

- **Routing, not resolution.** An allow-list validates the *address*, not the
  *route*. A "public" IP that the host's routing table sends to an internal
  network is invisible to this fix. Mitigation for high-assurance deployments
  is OS-level (`SO_BINDTODEVICE`, a network namespace, or an egress proxy) —
  out of scope, but worth a line in SECURITY.md.
- **The recursive resolver is trusted.** We validate *its* answers and pin them.
  A resolver that returns public IPs is fine (we dial public); a resolver that
  returns private IPs is blocked. What we cannot do is know the resolver lied
  about *which* public IP the name maps to — that is a correctness issue, not
  SSRF.
- **Proxy path** remains un-pinned unless the separate proxy item lands
  (`trust_env=False` recommended as the immediate hardening).
