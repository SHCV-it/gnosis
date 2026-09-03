# Design — SSRF IP pinning: **IPv6-mapped & dual-stack correctness**

Panel item: **pin-v6**. Author: SSRF panel member. Status: proposal.
Scope: `gnosis/core/network.py` (the `_is_private_address` classifier and the
`PinnedNetworkBackend.connect_tcp` candidate loop), plus `tests/test_network.py`.
Cross-refs: `design-ssrf-ip-pinning.md` (**pin-dns**, the resolution fix) and
`design-ssrf-ip-pinning-keepalive.md` (**pin-pool**, the pool/keep-alive
dimension).

## Verdict

Pinning the socket to the validated IP literal (pin-dns) is the right fix and I
endorse it. **But the allow-list pin-dns proposes in §4 is wrong for IPv6**, and
shipping it as written would introduce three SSRF primitives the *current*
block-list already blocks. Concretely, on Python 3.12.13 (this repo):

`not addr.is_global` **allows** NAT64 (`64:ff9b::/96`), IPv4-compatible
(`::/96`), and **multicast** (`ff00::/8`) — all three report `is_global=True`.

The correct rule is a **mapped/embedded-aware allow-list**: first unwrap every
IPv6 form that embeds an IPv4 address in its low 32 bits, then block
`not is_global or is_reserved or is_multicast or is_unspecified`. That single
change closes both the IPv4 gap the current code has live today (CGNAT
`100.64.0.0/10`) *and* the three IPv6 gaps pin-dns §4 would open. On the dial
side, dual-stack fallback must (a) keep the whole validated set in
`getaddrinfo` order and (b) normalize mapped addresses to their embedded IPv4
before dialing — and the sequential loop needs the deadline budget pin-pool
already flagged (F1), because the v6-first RFC 6724 order makes a broken-IPv6
host stall the full `timeout` before IPv4 is ever tried.

---

## 1. Verified classification matrix (Python 3.12.13, `ipaddress`)

Measured, not asserted. This is the ground truth the classifier must satisfy.

| Address | `is_private` | `is_global` | `is_reserved` | `is_multicast` | current blocklist | pin-dns `not is_global` | correct rule |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| `8.8.8.8` | F | **T** | F | F | allow | allow | **allow** |
| `100.64.0.1` (CGNAT) | F | F | F | F | **ALLOW ← live bug** | block | **block** |
| `::ffff:127.0.0.1` (mapped loopback) | T | F | F | F | block | block | **block** |
| `::ffff:8.8.8.8` (mapped public) | F | T | F | F | allow | allow | **allow** |
| `::127.0.0.1` (IPv4-compatible) | F | **T** | T | F | block (via `is_reserved`) | **ALLOW ← bug** | **block** |
| `64:ff9b::169.254.169.254` (NAT64 metadata) | F | **T** | T | F | block (via `is_reserved`) | **ALLOW ← bug** | **block** |
| `64:ff9b::127.0.0.1` (NAT64 loopback) | F | **T** | T | F | block (via `is_reserved`) | **ALLOW ← bug** | **block** |
| `64:ff9b:1::127.0.0.1` (NAT64 local-use) | T | F | T | F | block | block | **block** |
| `2002:7f00:1::` (6to4 of 127.0.0.1) | T | F | F | F | block | block | **block** |
| `2001:0000:…` (Teredo) | T | F | F | F | block | block | **block** |
| `fc00::1` (ULA) / `::1` / `::` / `fe80::1` | T | F | — | — | block | block | **block** |
| `ff02::1`, `ff0e::1` (multicast) | F | **T** | F | **T** | block (via `is_multicast`) | **ALLOW ← bug** | **block** |
| `2001:4860:4860::8888` (Google DNS) | F | T | F | F | allow | allow | **allow** |
| `4000::1` (`4000::/3`, IANA-reserved) | F | T | T | F | block (via `is_reserved`) | **ALLOW ← bug** | **block** |

Two structural facts explain the table:

1. **`is_global` for IPv6 is literally `not is_private`** (Python source,
   `IPv6Address.is_global.fget`: `return not self.is_private` after the
   `ipv4_mapped` delegation). It is *not* "global unicast". So any
   special-use prefix Python does not list as private — NAT64, IPv4-compatible,
   global-scope multicast, `4000::/3` — reports `is_global=True`.
2. **The current block-list survives on IPv6 only by luck of `is_reserved` /
   `is_multicast`.** NAT64 and IPv4-compatible happen to be in
   `_reserved_networks`; multicast happens to be checked explicitly. That luck
   is not portable and, more importantly, the *same* block-list is blind to
   IPv4 CGNAT — so the current code is not safe either, just unsafe in the
   other family.

Net: neither "keep the block-list" nor "switch to bare `not is_global`" is
correct. The rule below is the intersection that is correct in **both**
families.

---

## 2. Why the three IPv6 gaps matter (SSRF, not theory)

- **NAT64 `64:ff9b::/96`** (RFC 6052) — this is the realistic one. On an
  IPv6-only host behind a NAT64 gateway, connecting to `64:ff9b::a.b.c.d` is
  translated by the local gateway into an IPv4 connection to `a.b.c.d`. So
  `64:ff9b::169.254.169.254` reaches the cloud metadata service and
  `64:ff9b::127.0.0.1` reaches loopback. `is_global=True`, so pin-dns §4 would
  dial it. This is a well-documented SSRF bypass and it is the exact "handle
  IPv6-mapped correctly" case this panel item exists for.
- **IPv4-compatible `::/96`** (deprecated by RFC 4291 but still parsed and
  occasionally honored) — `::127.0.0.1` / `::169.254.169.254` embed an IPv4
  address that some stacks route to IPv4. `is_global=True`, same failure.
- **Multicast `ff00::/8`** — not an SSRF primitive (a `connect()` to a
  multicast group does not reach a unicast service), but `is_global=True` means
  bare `not is_global` would treat `ff02::1` as a public dial target. It must
  stay blocked; a scraper only ever dials unicast.

The IPv4-translatable local-use prefix `64:ff9b:1::/48` (RFC 8215) and 6to4 /
Teredo are already `is_private=True` on 3.12, so `not is_global` catches them —
but I keep them in the explicit embedding check anyway (§3) so the guard does
not depend on Python's private-network registry staying comprehensive across
versions.

---

## 3. The correct classifier

Replace `_is_private_address` in `gnosis/core/network.py` with an
embedded-aware allow-list. The rule: **the only thing a scraper may dial is a
plain global-unicast address; everything else — including every form that
embeds an IPv4 address — is blocked.**

```python
# IPv6 prefixes whose low 32 bits embed an IPv4 address that the stack may
# route *as* that IPv4 (mapped, compatible, NAT64). Classify the embedded
# address, never the wrapper.
_IPV4_EMBEDDING_V6 = (
    ipaddress.IPv6Network("::ffff:0:0/96"),  # IPv4-mapped (RFC 4291)
    ipaddress.IPv6Network("::/96"),          # IPv4-compatible (deprecated)
    ipaddress.IPv6Network("64:ff9b::/96"),   # NAT64 well-known (RFC 6052)
    ipaddress.IPv6Network("64:ff9b:1::/48"), # NAT64 local-use (RFC 8215)
)


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if addr.ipv4_mapped is not None:                 # ::ffff:a.b.c.d
        return addr.ipv4_mapped
    if addr in _IPV4_EMBEDDING_V6:
        return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return None


def _is_private_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Allow-list: plain global unicast only.

    Unwraps IPv4-mapped / -compatible / NAT64 addresses to the embedded IPv4,
    then blocks everything that is not a normal globally-reachable unicast
    address. Fail-closed: any ambiguity blocks.
    """
    if addr.version == 6:
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            addr = embedded
    return (
        not addr.is_global          # RFC1918, loopback, link-local, ULA,
                                    # CGNAT 100.64/10, 6to4, Teredo, docs, …
        or addr.is_reserved         # ::/96, 64:ff9b::/96, 4000::/3, 0/8, 240/4 …
        or addr.is_multicast        # ff00::/8 (is_global=True — must be explicit)
        or addr.is_unspecified       # ::, 0.0.0.0 (is_global=False, belt+suspenders)
    )
```

Why each term, mapped to the matrix:

- `not addr.is_global` — the workhorse, and the **only** part of the current
  code that is wrong today: it is what closes CGNAT `100.64.0.0/10`, which the
  current six-flag block-list misses (`is_private=False`, `is_global=False`,
  `is_reserved=False`). It also keeps RFC1918, loopback, link-local, ULA, 6to4,
  Teredo, and documentation blocked, and correctly **allows** mapped public
  (`::ffff:8.8.8.8` → embedded `8.8.8.8` → global).
- `addr.is_reserved` — the term pin-dns §4 dropped by using bare `is_global`.
  It is what blocks NAT64 `64:ff9b::/96`, IPv4-compatible `::/96`, and
  `4000::/3`. Do **not** remove it.
- `addr.is_multicast` — non-negotiable: `ff00::/8` has `is_global=True`.
- `addr.is_unspecified` — already covered by `not is_global`, kept as explicit
  documentation of intent.

This is strictly tighter than both the current block-list and pin-dns §4, and
it stays correct if Python's `_reserved_networks` / `_private_networks`
registries drift across versions (the `_IPV4_EMBEDDING_V6` tuple pins the
critical NAT64/compatible cases explicitly).

---

## 4. Dual-stack dial path (the `connect_tcp` candidate loop)

The current loop collects `info[4][0]` strings and drops everything else. Three
changes, in order of importance:

**4a. Normalize mapped/embedded addresses before dialing.** When classification
unwraps `::ffff:8.8.8.8` (public), the current code still dials the `::ffff:`
form. It works on Linux, but it is the one place a mapped wrapper can still
leak into the socket, and it is sloppy. Dial the unwrapped IPv4 instead — the
address that was actually validated is the address that must go on the wire:

```python
def _dial_address(addr: ipaddress._BaseAddress) -> str:
    if addr.version == 6:
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            return str(embedded)
    return str(addr)
```

**4b. Keep the full validated set, in `getaddrinfo` order, deduped by dial
address.** `getaddrinfo(..., type=SOCK_STREAM)` with no `family` filter returns
both A and AAAA, RFC 6724-ordered (IPv6 first on a dual-stack host). Preserve
that order for the sequential fallback; derive family from the dial string
(anyio re-parses it anyway), not from `info[0]`, so normalization can't produce
a family mismatch. Dedupe on the *normalized* dial string so a mapped and a
plain form of the same IPv4 collapse to one candidate.

**4c. Budget the deadline across candidates (pin-pool F1), or don't loop at
all.** The v6-first order means a dual-stack host with dead IPv6 burns the full
`timeout` on the AAAA candidate before the A candidate is attempted. That is a
per-fetch latency regression, not a security hole, but for a crawler it is a
real one. Endorse pin-pool §3a (budget `remaining = deadline - loop.time()` per
candidate). Optional and orthogonal: pass `flags=socket.AI_ADDRCONFIG` to
`getaddrinfo` so IPv6 answers are suppressed on hosts with no configured global
IPv6 — with the caveat that `AI_ADDRCONFIG` reflects *configured* interfaces,
not reachability, so it is a heuristic, never the security boundary.

Resulting loop (diff against the current `connect_tcp`):

```python
        candidates: list[str] = []
        seen: set[str] = set()
        for info in infos:
            ip = info[4][0]
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if _is_private_address(addr):
                _block(host, ip)
            dial = _dial_address(addr)
            if dial in seen:
                continue
            seen.add(dial)
            candidates.append(dial)
        # …then the existing sequential fallback, with pin-pool §3a's
        # deadline budget replacing the flat `timeout` per attempt.
```

The fail-closed "block if **any** returned address is private" contract is
unchanged and correct (pin-dns §2) — it is what makes the mixed public+private
dual-stack set unreachable, and it must be asserted for a *mixed-family* set
(public A + private AAAA) in tests, not just the IPv4-only case.

---

## 5. Acceptance criteria (testable, hermetic)

Add to `tests/test_network.py` (unit tests only; monkeypatch
`loop.getaddrinfo` exactly as the existing `test_resolves_once_and_pins_to_validated_ip`
does):

1. **NAT64 / compatible / multicast blocked as literals.**
   `check_ip_literal` / `PinnedNetworkBackend.connect_tcp` raise
   `PrivateNetworkBlocked` for `64:ff9b::169.254.169.254`, `64:ff9b::127.0.0.1`,
   `::127.0.0.1`, `::ffff:127.0.0.1`, `ff02::1`.
2. **CGNAT blocked.** `100.64.0.1` and `100.100.100.100` raise — this is the
   regression test that proves the current block-list gap is closed.
3. **Mapped public allowed and normalized.** `::ffff:8.8.8.8` is *not* blocked,
   and the dialed address is `8.8.8.8` (assert `_dial_address` / the candidate
   list), not the `::ffff:` form.
4. **Mixed-family fail-closed.** A resolver returning
   `[("2607:f8b0:…" public AAAA), ("10.0.0.1", private A)]` raises — one
   private answer poisons the whole set regardless of family.
5. **Dual-stack public both allowed, order preserved.** Resolver returns
   `[public AAAA, public A]` → both validated, candidates ordered AAAA-first,
   and `getaddrinfo` is called exactly once (the single-resolution invariant).
6. **Deadline budget.** A first candidate that times out falls back to the next
   within ~1×`timeout` (pin-pool AC-POOL-4), not `N×timeout`.
7. Existing pin-dns/pin-pool acceptance tests keep passing; `test_resolves_once_and_pins_to_validated_ip`
   (single resolution, dial == `["93.184.216.34"]`) is unaffected by the
   classifier change.

---

## 6. Residual risk (honest)

- **Address ≠ route.** The classifier validates the *address*, not the *route*
  to it; an OS routing table that sends a "public" address into an internal
  network is invisible to this fix (pin-dns §6 already flags this; keep it in
  SECURITY.md).
- **NAT64 is only reachable if the host actually has a NAT64 route.** The guard
  is fail-closed anyway (we block `64:ff9b::/96` unconditionally), so this is a
  *liveness* consideration (a legit IPv6-only scraper that only reaches the
  internet through NAT64 will now be blocked from IPv4-only sites by name —
  mitigation is a real IPv6 route or `--allow-private-network`, both explicit).
- **ORCHIDv2 `2001:20::/28`** still reports `is_global=True, is_reserved=False`
  on 3.12. It is an overlay-routed hash identifier, not an SSRF primitive
  (cannot be made to terminate on private space), so I do not add a carve-out
  for it — worth a comment, not code.
- **The recursive resolver is trusted** for *which* public IPs a name maps to
  (correctness, not SSRF) — unchanged from pin-dns §6.
