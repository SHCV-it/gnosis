"""Tests for the MCP server: core logic, lazy `mcp` import, and stdio introspection."""

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gnosis.config.settings import Settings
from gnosis.mcp_server import fetch_and_convert

PORT = 8948

PAGE = (
    b"<html><head><title>MCP Fixture</title></head><body><main>"
    b"<h1>MCP Fixture Page</h1><p>Substantial content for the MCP server test, "
    b"long enough to exceed the minimum content threshold in the converter so "
    b"the page is captured as content rather than boilerplate.</p></main></body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    srv.allow_reuse_address = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{PORT}/page"
    srv.shutdown()
    srv.server_close()


def test_fetch_and_convert_returns_provenance(server):
    settings = Settings()
    settings.downloader.allow_private_network = True
    settings.downloader.respect_robots = False
    result = asyncio.run(fetch_and_convert(server, settings))

    assert result["url"] == server
    assert result["status_code"] == 200
    assert "MCP Fixture Page" in result["markdown"]

    import hashlib
    assert result["content_hash"] == hashlib.sha256(result["markdown"].encode("utf-8")).hexdigest()
    assert result["bytes_sha256"] == hashlib.sha256(PAGE).hexdigest()
    assert result["fetched_at"].endswith("Z")


def test_default_settings_block_private_network(server):
    """Regression (reviewer P0): with default settings, an internal literal must
    be blocked by the SSRF guard — the MCP tool must not probe private nets."""
    from gnosis.core.network import PrivateNetworkBlocked
    settings = Settings()
    with pytest.raises(PrivateNetworkBlocked):
        asyncio.run(fetch_and_convert(server, settings))


def test_main_fails_cleanly_without_mcp(monkeypatch):
    """mcp must be lazy: main() raises a clean SystemExit when it is absent."""
    import builtins

    from gnosis.mcp_server import main

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("no mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as exc:
        main()
    assert "mcp" in str(exc.value)


def _read_jsonrpc_response(proc, expected_id, timeout=15):
    """Read stdout lines until a JSON-RPC response with the expected id arrives."""
    import json

    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == expected_id:
            return msg
    raise AssertionError(f"no JSON-RPC response for id={expected_id}")


def test_stdio_server_responds_to_introspection():
    """Glama (and every MCP client) checks: the server must start and answer
    `initialize` + `tools/list` over stdio. Lock that contract in."""
    import json
    import os
    import shutil
    import subprocess
    import sys

    exe = os.path.join(os.path.dirname(sys.executable), "gnosis-mcp")
    if not os.path.exists(exe):
        exe = shutil.which("gnosis-mcp")
    if not exe:
        pytest.skip("gnosis-mcp console script not installed (mcp extra missing)")

    proc = subprocess.Popen(
        [exe],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "glama-introspection", "version": "1.0"},
            },
        }) + "\n")
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        }) + "\n")
        proc.stdin.flush()

        init_resp = _read_jsonrpc_response(proc, 1)
        assert "serverInfo" in init_resp["result"], init_resp

        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }) + "\n")
        proc.stdin.flush()
        tools_resp = _read_jsonrpc_response(proc, 2)
        names = [t["name"] for t in tools_resp["result"]["tools"]]
        assert "fetch_and_convert" in names, names
    finally:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
