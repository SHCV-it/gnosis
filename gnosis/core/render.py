"""Optional JS-rendering backends via sidecar subprocess.

Gnosis is static-first (httpx). When a page is client-rendered (a SPA), an
optional renderer produces the post-JS DOM. Rendering is an opt-in extra:
the renderer is a separate binary (e.g. Obscura) invoked as a subprocess,
so the core install carries no browser dependency.

A RenderResult carries its own provenance (engine, version, timestamp,
js_executed) so downstream files record *how* content was obtained.
"""

import asyncio
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime


class RenderError(Exception):
    """Raised when a render backend fails."""


@dataclass
class RenderResult:
    """Output of a render backend."""

    html: str
    engine: str = ""
    version: str = ""
    render_timestamp: str = ""
    js_executed: bool = True


class ObscuraRenderer:
    """Render via the `obscura` CLI (subprocess sidecar)."""

    def __init__(self, binary: str = "obscura", timeout: float = 30.0) -> None:
        self.binary = binary
        self.timeout = timeout
        self.version = ""

    async def _get_version(self) -> str:
        if not self.version:
            try:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    [self.binary, "--version"],
                    capture_output=True,
                    timeout=5,
                )
                self.version = proc.stdout.decode("utf-8", errors="replace").strip() or "unknown"
            except Exception:
                self.version = "unknown"
        return self.version

    async def render(self, url: str) -> RenderResult:
        cmd = [
            self.binary,
            "fetch",
            url,
            "--dump",
            "html",
            "--wait-until",
            "networkidle0",
            "--quiet",
        ]
        try:
            proc = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, timeout=self.timeout
            )
        except FileNotFoundError as exc:
            raise RenderError(f"renderer binary not found: {self.binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RenderError(f"render timed out after {self.timeout}s: {url}") from exc

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RenderError(f"renderer exited {proc.returncode}: {stderr}")

        return RenderResult(
            html=proc.stdout.decode("utf-8", errors="replace"),
            engine="obscura",
            version=await self._get_version(),
            render_timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            js_executed=True,
        )
