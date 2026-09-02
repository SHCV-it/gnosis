"""SSRF / private-network guards for outbound requests.

Blocks requests targeting loopback, private (RFC 1918), link-local,
multicast, reserved, and unspecified addresses — the classic SSRF target
set (cloud metadata 169.254.169.254, localhost services, internal ranges).

IPv4-mapped IPv6 addresses (``::ffff:a.b.c.d``) are unwrapped before the
check so they cannot bypass it.

Security boundary
-----------------
The authoritative enforcement point is :class:`PinnedNetworkBackend`, which
resolves a hostname **once**, validates *every* returned address, and then
connects to one of those validated addresses. This closes the DNS-rebinding
TOCTOU: the address that is validated is the exact address that is dialed —
the transport never performs a second, independent resolution that an
attacker-controlled resolver could answer differently.

:func:`assert_public_url` remains as an advisory pre-flight helper (and is
used directly by tests); it is *not* the security boundary. Do not rely on
validate-then-connect patterns that resolve a hostname, validate, and then
let a separate resolver decide the connect address.
"""

import asyncio
import ipaddress
import socket
import ssl
import typing
from urllib.parse import urlparse

import httpcore
import httpx
from httpcore import ConnectError, ConnectTimeout
from httpcore._backends.anyio import AnyIOBackend  # internal; subclassed for socket setup
from httpx._config import DEFAULT_LIMITS, create_ssl_context  # internal; mirrors httpx transport TLS config
from httpx._transports.default import (  # internal; mirrors httpx's own transport
    AsyncResponseStream,
    map_httpcore_exceptions,
)


class PrivateNetworkBlocked(Exception):
    """Raised when a request targets a private/reserved network address."""


def _is_private_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _block(host: str, ip: str | None = None) -> typing.NoReturn:
    target = f"{host} -> {ip}" if ip else host
    raise PrivateNetworkBlocked(f"blocked private/reserved address: {target}")


def check_ip_literal(host: str) -> None:
    """Raise PrivateNetworkBlocked if ``host`` is a private/reserved IP literal.

    Synchronous and DNS-free: this is a fast-fail for literal addresses only.
    Hostnames are *not* resolved here — resolution is the pinned backend's job.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return  # not an IP literal
    if _is_private_address(addr):
        _block(host)


async def assert_public_url(url: str) -> None:
    """Advisory pre-flight: raise PrivateNetworkBlocked if the URL is private.

    NOTE: this is not the security boundary. It resolves and validates, then a
    transport that resolves *again* could still be rebound. The enforced guard
    is :class:`PinnedNetworkBackend` (see module docstring). This helper is
    retained for IP-literal fast-fails and direct use in tests.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if host is None:
        return

    # Fast path: IP literal.
    try:
        addr = ipaddress.ip_address(host)
        if _is_private_address(addr):
            _block(host)
        return
    except ValueError:
        pass  # not an IP literal -> resolve below

    # Hostname: reject if ANY resolved address is private.
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        port = 80
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return  # resolution failure -> let the request fail naturally
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if _is_private_address(addr):
            _block(host, ip)


class PinnedNetworkBackend(AnyIOBackend):
    """httpcore network backend that pins DNS resolution to validated IPs.

    Subclasses httpcore's anyio backend so every socket is created exactly as
    httpcore would (timeout handling, TCP_NODELAY, socket options, exception
    mapping). It overrides only the resolution step: a hostname is resolved
    once, *all* returned addresses are validated, and the connect proceeds
    against those validated IP literals only.

    Because httpcore performs TLS with ``server_hostname`` set to the original
    hostname (not the dialed IP), pinning to an IP does not weaken certificate
    verification or SNI.
    """

    def __init__(self, *, allow_private_network: bool = False) -> None:
        super().__init__()
        self.allow_private_network = allow_private_network

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[tuple] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if self.allow_private_network:
            return await super().connect_tcp(host, port, timeout, local_address, socket_options)

        # Fast path: IP literal (no DNS, no rebinding surface).
        try:
            addr = ipaddress.ip_address(host)
            if _is_private_address(addr):
                _block(host)
            return await super().connect_tcp(host, port, timeout, local_address, socket_options)
        except ValueError:
            pass  # hostname -> resolve below

        # Resolve once. Any private address in the answer set => block (fail
        # closed against a resolver that mixes public+private to win a race).
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ConnectError(f"DNS resolution failed for {host}: {exc}") from exc

        candidates: list[str] = []
        seen: set[str] = set()
        for info in infos:
            ip = info[4][0]
            if ip in seen:
                continue
            seen.add(ip)
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if _is_private_address(addr):
                _block(host, ip)
            candidates.append(ip)

        if not candidates:
            raise ConnectError(f"no public address resolved for {host}")

        # Pin: dial the validated IP literals only. Budget the per-attempt
        # timeout from one overall deadline so a dual-stack host whose first
        # candidate is unreachable (dead IPv6 + live IPv4 is common) cannot
        # multiply the connect timeout across candidates.
        deadline = loop.time() + timeout if timeout is not None else None
        last_error: Exception | None = None
        for ip in candidates:
            remaining: float | None = None
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
            try:
                return await super().connect_tcp(ip, port, remaining, local_address, socket_options)
            except (ConnectError, ConnectTimeout) as exc:
                last_error = exc
                continue
        raise ConnectError(f"failed to connect to {host}: {last_error}")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: typing.Iterable[tuple] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if self.allow_private_network:
            return await super().connect_unix_socket(path, timeout, socket_options)
        # A Unix domain socket bypasses TCP/IP addressing entirely; fail closed.
        raise PrivateNetworkBlocked(
            "Unix domain sockets are disabled while the SSRF guard is enabled"
        )


class SSRFPinnedTransport(httpx.AsyncBaseTransport):
    """httpx transport that routes connections through :class:`PinnedNetworkBackend`.

    Built on ``httpcore.AsyncConnectionPool`` (the same pool httpx's default
    transport uses) with a pinned network backend. Handles only the direct
    (no-proxy) case — gnosis never configures a proxy; a proxy would move DNS
    resolution to the proxy and invalidate client-side pinning, so it is
    deliberately unsupported here.
    """

    def __init__(
        self,
        *,
        verify: ssl.SSLContext | str | bool = True,
        cert: typing.Any = None,
        trust_env: bool = True,
        http1: bool = True,
        http2: bool = False,
        limits: httpx.Limits | None = None,
        retries: int = 0,
        local_address: str | None = None,
        allow_private_network: bool = False,
        socket_options: typing.Iterable[tuple] | None = None,
    ) -> None:
        limits = limits or DEFAULT_LIMITS
        ssl_context = create_ssl_context(verify=verify, cert=cert, trust_env=trust_env)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=http1,
            http2=http2,
            retries=retries,
            local_address=local_address,
            network_backend=PinnedNetworkBackend(allow_private_network=allow_private_network),
            socket_options=socket_options,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.AsyncByteStream)

        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        with map_httpcore_exceptions():
            resp = await self._pool.handle_async_request(req)

        assert isinstance(resp.stream, typing.AsyncIterable)
        return httpx.Response(
            status_code=resp.status,
            headers=resp.headers,
            stream=AsyncResponseStream(resp.stream),
            extensions=resp.extensions,
        )

    async def __aenter__(self) -> "SSRFPinnedTransport":
        await self._pool.__aenter__()
        return self

    async def __aexit__(self, *exc: typing.Any) -> None:
        with map_httpcore_exceptions():
            await self._pool.__aexit__(*exc)

    async def aclose(self) -> None:
        await self._pool.aclose()


def build_transport(
    allow_private_network: bool, **kwargs: typing.Any
) -> httpx.AsyncBaseTransport | None:
    """Return a pinned SSRF-guarded transport, or ``None`` for httpx defaults.

    ``None`` (the stock httpx transport) is returned when private networks are
    allowed, preserving current behavior exactly when the guard is opted out.
    ``kwargs`` are forwarded to :class:`SSRFPinnedTransport` (e.g. ``limits``,
    ``http2``, ``retries``) so keep-alive/connection knobs are not silently
    dropped when callers start exposing them.
    """
    if allow_private_network:
        return None
    return SSRFPinnedTransport(**kwargs)
