"""Tests for the SSRF / private-network guard."""

import asyncio

import pytest

from gnosis.config.settings import DownloaderSettings
from gnosis.core.downloader import Downloader
from gnosis.core.network import PrivateNetworkBlocked, assert_public_url


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

        with pytest.raises(Exception) as exc:
            asyncio.run(_run())
        assert not isinstance(exc.value, PrivateNetworkBlocked)
