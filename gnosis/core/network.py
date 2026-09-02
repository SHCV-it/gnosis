"""SSRF / private-network guards for outbound requests.

Blocks requests targeting loopback, private (RFC 1918), link-local,
multicast, reserved, and unspecified addresses — the classic SSRF target
set (cloud metadata 169.254.169.254, localhost services, internal ranges).

IPv4-mapped IPv6 addresses (``::ffff:a.b.c.d``) are unwrapped before the
check so they cannot bypass it.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


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


async def assert_public_url(url: str) -> None:
    """Raise PrivateNetworkBlocked if the URL resolves to a private address."""
    parsed = urlparse(url)
    host = parsed.hostname
    if host is None:
        return

    # Fast path: IP literal.
    try:
        addr = ipaddress.ip_address(host)
        if _is_private_address(addr):
            raise PrivateNetworkBlocked(f"blocked private/reserved address: {host}")
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
            raise PrivateNetworkBlocked(f"blocked private/reserved address: {host} -> {ip}")
