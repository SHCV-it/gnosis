"""gnosis-bench: a reproducible evaluation scorecard for gnosis.

Fetches and converts a list of URLs, measuring per-URL provenance
completeness, latency, and content metrics, then emits an aggregate
scorecard as JSON and a rendered table.
"""

import asyncio
import json
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from gnosis.config.settings import Settings, load_config
from gnosis.core.converter import HTMLToMarkdownConverter
from gnosis.core.downloader import Downloader, DownloadError
from gnosis.core.network import PrivateNetworkBlocked
from gnosis.core.provenance import build_frontmatter

console = Console()

_CORE_PROVENANCE = {
    "url",
    "fetched_at",
    "content_hash",
    "bytes_sha256",
    "status_code",
    "generator",
}


@click.command()
@click.option(
    "--urls",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="File with one URL per line (# comments ignored).",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default="bench-report.json",
    show_default=True,
    help="JSON report path.",
)
@click.option("--concurrency", default=5, show_default=True, help="Max concurrent fetches.")
@click.option("-c", "--config", type=click.Path(exists=True, path_type=Path), help="YAML config file.")
def bench(urls: Path, output: Path, concurrency: int, config: Path | None) -> None:
    """Evaluate gnosis over a corpus of URLs and emit a scorecard."""
    settings = load_config(config)
    url_list = [
        ln.strip()
        for ln in urls.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    if not url_list:
        console.print("[red]✗[/red] No URLs found in file.")
        raise SystemExit(1)

    results = asyncio.run(_run(url_list, settings, concurrency))
    _emit(results, output, url_list)


async def _run(urls: list[str], settings: Settings, concurrency: int) -> list[dict]:
    downloader = Downloader(settings.downloader)
    converter = HTMLToMarkdownConverter(settings.converter)
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(url: str) -> dict:
        async with sem:
            start = time.perf_counter()
            try:
                fetch = await downloader.fetch_result(url)
                markdown = converter.convert(fetch.html, base_url=fetch.final_url)
                latency_ms = int((time.perf_counter() - start) * 1000)
                fm = build_frontmatter(
                    fetch, markdown, converter.extract_metadata(fetch.html)
                )
                return {
                    "url": url,
                    "status_code": fetch.status_code,
                    "latency_ms": latency_ms,
                    "raw_bytes": len(fetch.raw_bytes),
                    "markdown_chars": len(markdown),
                    "provenance_complete": _CORE_PROVENANCE <= set(fm),
                }
            except (DownloadError, PrivateNetworkBlocked) as exc:
                return {
                    "url": url,
                    "error": str(exc),
                    "status_code": None,
                    "latency_ms": None,
                    "raw_bytes": 0,
                    "markdown_chars": 0,
                    "provenance_complete": False,
                }

    try:
        return await asyncio.gather(*(one(u) for u in urls))
    finally:
        await downloader.close()


def _emit(results: list[dict], output: Path, url_list: list[str]) -> None:
    ok = [r for r in results if r.get("status_code") is not None]
    total = len(results)

    avg_latency = sum(r["latency_ms"] for r in ok) / len(ok) if ok else 0.0
    avg_ratio = (
        sum(r["markdown_chars"] / max(1, r["raw_bytes"]) for r in ok) / len(ok)
        if ok
        else 0.0
    )
    provenance_complete = sum(r["provenance_complete"] for r in ok)
    token_estimate = sum(r["markdown_chars"] for r in ok) // 4

    scorecard = {
        "corpus_size": total,
        "successful": len(ok),
        "success_rate": len(ok) / total if total else 0.0,
        "avg_latency_ms": round(avg_latency, 1),
        "avg_markdown_ratio": round(avg_ratio, 3),
        "provenance_complete": provenance_complete,
        "token_estimate": token_estimate,
        "per_url": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    table = Table(title="gnosis bench scorecard")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")
    table.add_row("Corpus size", str(total))
    table.add_row("Successful", f"{len(ok)}/{total}")
    table.add_row("Success rate", f"{scorecard['success_rate']:.1%}")
    table.add_row("Avg latency", f"{avg_latency:.1f} ms")
    table.add_row("Avg markdown/raw ratio", f"{avg_ratio:.3f}")
    table.add_row("Provenance complete", f"{provenance_complete}/{len(ok)}")
    table.add_row("Token estimate", str(token_estimate))
    console.print(table)
    console.print(f"[dim]Report: {output}[/dim]")


if __name__ == "__main__":
    bench()
