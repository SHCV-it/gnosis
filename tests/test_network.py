"""Tests for the SSRF / private-network guard."""

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from httpcore import ConnectError
from httpcore._backends.anyio import AnyIOBackend

from gnosis.config.settings import DownloaderSettings
from gnosis.core.downloader import Downloader
from gnosis.core.network import (
    PinnedNetworkBackend,
    PrivateNetworkBlocked,
    SSRFPinnedTransport,
    assert_public_url,
    build_transport,
)


class TestAssertPublicUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://172.16.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data",
            "http://0.0.0.0/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://224.0.0.1/",
            "http://240.0.0.1/",
            "http://[fc00::1]/",
            "http://[fe80::1]/",
        ],
    )
    def test_blocks_private_addresses(self, url):
        with pytest.raises(PrivateNetworkBlocked):
            asyncio.run(assert_public_url(url))

    def test_blocks_private_hostname(self):
        with pytest.raises(PrivateNetworkBlocked):
            asyncio.run(assert_public_url("http://localhost/"))

    @pytest.mark.parametrize(
        "url",
        [
            "http://93.184.216.34/",  # example.com
            "http://1.1.1.1/",
            "http://8.8.8.8/",
        ],
    )
    def test_allows_public_addresses(self, url):
        asyncio.run(assert_public_url(url))  # must not raise


class TestDownloaderGuard:
    def test_downloader_blocks_private_by_default(self):
        async def _run():
            async with Downloader(DownloaderSettings(rate_limit_ms=0)) as dl:
                return await dl.fetch_result("http://127.0.0.1:9/")

        with pytest.raises(PrivateNetworkBlocked):
            asyncio.run(_run())

    def test_downloader_allows_private_when_opted_in(self):
        async def _run():
            settings = DownloaderSettings(rate_limit_ms=0, retries=0, allow_private_network=True)
            async with Downloader(settings) as dl:
                return await dl.fetch_result("http://127.0.0.1:9/")

        try:
            asyncio.run(_run())
        except PrivateNetworkBlocked:
            pytest.fail("opted-in fetch must not be blocked by the SSRF guard")
        except Exception:
            pass

    def test_downloader_uses_pinned_transport(self):
        async def _run():
            async with Downloader(DownloaderSettings(rate_limit_ms=0)) as dl:
                client = await dl._get_client()
                assert isinstance(client._transport, SSRFPinnedTransport)

        asyncio.run(_run())


class TestPinnedNetworkBackend:
    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "::ffff:127.0.0.1"],
    )
    def test_blocks_private_ip_literal(self, host):
        backend = PinnedNetworkBackend()
        with pytest.raises(PrivateNetworkBlocked):
            asyncio.run(backend.connect_tcp(host, 80))

    def test_blocks_private_hostname(self):
        # 'localhost' resolves to loopback; the backend must block before dialing.
        backend = PinnedNetworkBackend()
        with pytest.raises(PrivateNetworkBlocked):
            asyncio.run(backend.connect_tcp("localhost", 80))

    def test_resolves_once_and_pins_to_validated_ip(self, monkeypatch):
        backend = PinnedNetworkBackend()
        resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        getaddrinfo = AsyncMock(return_value=resolved)
        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", getaddrinfo)

        dialed = []

        async def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
            dialed.append(host)
            return object()

        monkeypatch.setattr(AnyIOBackend, "connect_tcp", fake_connect)

        asyncio.run(backend.connect_tcp("rebind.example", 80))

        # The resolver is consulted exactly once (no second resolve-then-connect),
        # and the dial targets the validated IP literal, not the hostname.
        assert getaddrinfo.await_count == 1
        assert dialed == ["93.184.216.34"]

    def test_blocks_if_any_resolved_address_is_private(self, monkeypatch):
        backend = PinnedNetworkBackend()
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 80)),
        ]
        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", AsyncMock(return_value=resolved))

        with pytest.raises(PrivateNetworkBlocked):
            asyncio.run(backend.connect_tcp("rebind.example", 80))

    def test_sequential_fallback_budgets_timeout_across_candidates(self, monkeypatch):
        # F1: a dual-stack host whose first candidate is unreachable must not
        # multiply the connect timeout. The second candidate receives the
        # *remaining* budget, not a fresh full timeout.
        backend = PinnedNetworkBackend()
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 80)),
        ]
        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", AsyncMock(return_value=resolved))

        calls = {"n": 0}
        timeouts = []

        async def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
            calls["n"] += 1
            timeouts.append((host, timeout))
            if calls["n"] == 1:
                await asyncio.sleep(0.05)
                raise ConnectError("boom")
            return object()

        monkeypatch.setattr(AnyIOBackend, "connect_tcp", fake_connect)

        asyncio.run(backend.connect_tcp("dual.example", 80, timeout=10.0))

        assert calls["n"] == 2
        assert timeouts[0][0] == "93.184.216.34"
        assert timeouts[1][0] == "1.1.1.1"
        # First attempt gets ~the full budget; second gets measurably less.
        assert timeouts[0][1] is not None and timeouts[0][1] <= 10.0
        assert timeouts[1][1] is not None
        assert timeouts[1][1] < timeouts[0][1] - 0.01

    def test_allow_private_network_skips_validation(self, monkeypatch):
        backend = PinnedNetworkBackend(allow_private_network=True)
        dialed = []

        async def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
            dialed.append(host)
            return object()

        monkeypatch.setattr(AnyIOBackend, "connect_tcp", fake_connect)
        asyncio.run(backend.connect_tcp("127.0.0.1", 80))
        assert dialed == ["127.0.0.1"]


class TestSSRFPinnedTransport:
    def test_transport_blocks_private_literal(self):
        async def _run():
            async with httpx.AsyncClient(transport=SSRFPinnedTransport(), timeout=1.0) as client:
                await client.get("http://127.0.0.1:9/")

        with pytest.raises(PrivateNetworkBlocked):
            asyncio.run(_run())

    def test_build_transport_returns_none_when_allowed(self):
        assert build_transport(True) is None
        assert isinstance(build_transport(False), SSRFPinnedTransport)
