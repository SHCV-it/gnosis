"""
Main CLI module for Gnosis.

Provides the command-line interface using Click.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click
from rich.console import Console

from gnosis import __version__
from gnosis.config import Settings, load_config
from gnosis.core.downloader import Downloader
from gnosis.core.converter import HTMLToMarkdownConverter
from gnosis.core.crawler import Crawler

console = Console()


def url_to_filename(url: str, base_url: Optional[str] = None) -> str:
    """
    Convert a URL to a safe filename.

    Args:
        url: The URL to convert.
        base_url: The base URL for relative path calculation.

    Returns:
        A safe filename string.

    Examples:
        https://docs.openclaw.ai/ -> docs.openclaw.ai.md
        https://docs.openclaw.ai/start/getting-started -> docs.openclaw.ai-start-getting-started.md
    """
    parsed = urlparse(url)
    domain = parsed.netloc

    # Get path and clean it
    path = parsed.path.strip("/")

    if not path:
        return domain

    # Convert path to slug
    path_slug = path.replace("/", "-")

    return f"{domain}-{path_slug}"


@click.command()
@click.argument("url")
@click.option(
    "--all",
    "-a",
    "crawl_all",
    is_flag=True,
    help="Download all child pages under the same URL path.",
)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to YAML configuration file.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory for markdown files.",
)
@click.option(
    "--overwrite",
    "-f",
    is_flag=True,
    help="Overwrite existing output files.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress progress output.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed conversion process information.",
)
@click.version_option(version=__version__, prog_name="gnosis")
def cli(
    url: str,
    crawl_all: bool,
    config: Optional[Path],
    output: Optional[Path],
    overwrite: bool,
    quiet: bool,
    verbose: bool,
):
    """
    Download websites and convert them to LLM-friendly markdown.

    URL is the website address to download and convert.

    \b
    Examples:
        gnosis https://docs.example.com/
        gnosis https://docs.example.com/ --all
        gnosis https://docs.example.com/ -o ./docs/
    """
    # Load configuration
    settings = load_config(config)

    # Override settings from CLI options
    if output:
        settings.output.directory = str(output)
    if overwrite:
        settings.output.overwrite = True

    # Ensure output directory exists
    output_dir = Path(settings.output.directory)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run the appropriate mode
    if crawl_all:
        asyncio.run(crawl_and_convert(url, settings, quiet, verbose))
    else:
        asyncio.run(download_and_convert(url, settings, quiet, verbose))


async def download_and_convert(url: str, settings: Settings, quiet: bool, verbose: bool) -> None:
    """Download a single page and convert to markdown."""
    downloader = Downloader(settings.downloader)
    converter = HTMLToMarkdownConverter(settings.converter, verbose=verbose)

    if not quiet:
        console.print(f"[blue]📥[/blue] Downloading: {url}")

    try:
        html = await downloader.fetch(url)
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to download: {e}")
        sys.exit(1)

    if not quiet:
        console.print("[blue]🔄[/blue] Converting to markdown...")

    markdown = converter.convert(html, base_url=url)

    # Generate output filename
    output_dir = Path(settings.output.directory)
    filename = url_to_filename(url) + settings.output.extension
    output_path = output_dir / filename

    # Check if file exists
    if output_path.exists() and not settings.output.overwrite:
        console.print(f"[yellow]⚠[/yellow] File exists: {output_path}")
        console.print("Use --overwrite to replace existing files.")
        sys.exit(1)

    # Save output
    output_path.write_text(markdown, encoding="utf-8")

    if not quiet:
        console.print(f"[green]✓[/green] Saved: {output_path}")


async def crawl_and_convert(url: str, settings: Settings, quiet: bool, verbose: bool) -> None:
    """Crawl all child pages and convert each to markdown."""
    downloader = Downloader(settings.downloader)
    converter = HTMLToMarkdownConverter(settings.converter, verbose=verbose)
    crawler = Crawler(settings.crawler, downloader)

    if not quiet:
        console.print(f"[blue]🕷[/blue] Crawling: {url}")
        console.print(
            f"    Max depth: {settings.crawler.max_depth}, "
            f"Max pages: {settings.crawler.max_pages}"
        )

    output_dir = Path(settings.output.directory)
    saved_count = 0
    skipped_count = 0

    async for page_url, html in crawler.crawl(url):
        if not quiet:
            console.print(f"[blue]📥[/blue] Downloaded: {page_url}")

        markdown = converter.convert(html, base_url=page_url)

        # Generate output filename
        filename = url_to_filename(page_url, base_url=url) + settings.output.extension
        output_path = output_dir / filename

        # Check if file exists
        if output_path.exists() and not settings.output.overwrite:
            if not quiet:
                console.print(f"[yellow]⚠[/yellow] Skipped (exists): {output_path}")
            skipped_count += 1
            continue

        # Save output
        output_path.write_text(markdown, encoding="utf-8")
        saved_count += 1

        if not quiet:
            console.print(f"[green]✓[/green] Saved: {output_path}")

    if not quiet:
        console.print()
        console.print(f"[green]✅[/green] Complete!")
        console.print(f"    Saved: {saved_count} files")
        if skipped_count > 0:
            console.print(f"    Skipped: {skipped_count} files (already exist)")


def main():
    """Main entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠[/yellow] Interrupted by user")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
