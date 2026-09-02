"""
Main CLI module for Gnosis.

Provides the command-line interface using Click.
"""

import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click
import yaml
from rich.console import Console

from gnosis import __version__
from gnosis.config import Settings, load_config
from gnosis.config.settings import AuthSettings, expand_env
from gnosis.core.archive import Archiver
from gnosis.core.checkpoint import load_checkpoint, save_checkpoint
from gnosis.core.converter import MIN_CONTENT_THRESHOLD, HTMLToMarkdownConverter
from gnosis.core.crawler import Crawler
from gnosis.core.downloader import Downloader, RobotsDisallowed
from gnosis.core.llms import fetch_sitemap_urls, render_llms_full, render_llms_txt
from gnosis.core.network import PrivateNetworkBlocked
from gnosis.core.provenance import build_frontmatter, compute_bytes_hash, compute_content_hash, render_document
from gnosis.core.render import ObscuraRenderer, RenderError

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
    domain = parsed.netloc.replace(":", "-")

    # Get path and clean it
    path = parsed.path.strip("/")

    if not path and not parsed.query:
        return domain

    # Convert path to slug; replace / and : for cross-platform filename safety
    path_slug = path.replace("/", "-").replace(":", "-")

    base = f"{domain}-{path_slug}" if path else domain

    # Append short hash when query parameters are present to avoid filename collisions
    if parsed.query:
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        return f"{base}-{url_hash}"

    return base


def url_to_collection_name(url: str) -> str:
    """
    Convert a URL to a QMD collection name.

    Args:
        url: The URL to convert.

    Returns:
        A sanitized collection name.

    Examples:
        https://docs.example.com/ -> docs-example-com
        https://docs.example.com/api/v2 -> docs-example-com-api-v2
    """
    parsed = urlparse(url)
    domain = parsed.netloc
    path = parsed.path.strip("/")

    # Combine domain and path
    if path:
        name = f"{domain}/{path}"
    else:
        name = domain

    # Sanitize: lowercase, replace special chars with hyphens
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    name = name.strip('-')

    return name


def _parse_frontmatter_extras(pairs: tuple[str, ...]) -> dict:
    """
    Parse repeated 'KEY: VALUE' CLI options into a dict.

    Values are parsed as YAML scalars/collections so types survive
    (e.g. 'tags: [a, b]' -> list, 'draft: true' -> bool).

    Args:
        pairs: Tuple of "KEY: VALUE" strings.

    Returns:
        Dict of extra frontmatter fields.
    """
    extras: dict = {}
    for pair in pairs:
        if ":" not in pair:
            console.print(f"[red]✗[/red] Invalid --frontmatter value (expected KEY: VALUE): {pair}")
            sys.exit(1)
        key, _, raw_value = pair.partition(":")
        key = key.strip()
        if not key:
            console.print(f"[red]✗[/red] Empty --frontmatter key in: {pair}")
            sys.exit(1)
        try:
            parsed = yaml.safe_load(f"{key}: {raw_value.strip()}")
            extras[key] = parsed[key]
        except yaml.YAMLError:
            extras[key] = raw_value.strip()
    return extras


def _apply_cli_auth(
    settings: Settings,
    *,
    extra_headers: tuple[str, ...],
    bearer_token_env: Optional[str],
    basic_user: Optional[str],
    basic_token_env: Optional[str],
) -> None:
    """
    Apply CLI-provided auth and custom headers onto downloader settings.

    Secrets are always read from environment variables, never from CLI
    arguments directly (which would leak into shell history and logs).

    Args:
        settings: Settings object to mutate.
        extra_headers: Repeated "Name: Value" header strings (${VAR} expanded).
        bearer_token_env: Env var name holding a bearer token.
        basic_user: HTTP Basic username.
        basic_token_env: Env var name holding the Basic password/token.
    """
    import os

    for header in extra_headers:
        if ":" not in header:
            console.print(f"[red]✗[/red] Invalid --header value (expected Name: Value): {header}")
            sys.exit(1)
        name, _, value = header.partition(":")
        settings.downloader.headers[name.strip()] = expand_env(value.strip())

    if bearer_token_env:
        token = os.environ.get(bearer_token_env, "")
        if not token:
            console.print(f"[red]✗[/red] Env var {bearer_token_env} is not set (needed for --bearer-token-env)")
            sys.exit(1)
        settings.downloader.auth = AuthSettings(type="bearer", token=token)
    elif basic_user or basic_token_env:
        if not (basic_user and basic_token_env):
            console.print("[red]✗[/red] --basic-user and --basic-token-env must be used together")
            sys.exit(1)
        token = os.environ.get(basic_token_env, "")
        if not token:
            console.print(f"[red]✗[/red] Env var {basic_token_env} is not set (needed for --basic-token-env)")
            sys.exit(1)
        settings.downloader.auth = AuthSettings(
            type="basic", username=basic_user, password=token
        )


def _render_output(fetch, markdown: str, metadata: dict, settings: Settings) -> str:
    """
    Render the final document: markdown body, with provenance frontmatter
    unless disabled.

    Args:
        fetch: FetchResult for the page.
        markdown: Converted markdown body.
        metadata: Extracted page metadata dict.
        settings: Current settings.

    Returns:
        Document string ready to write.
    """
    if not settings.output.frontmatter:
        return markdown if markdown.endswith("\n") else markdown + "\n"
    frontmatter = build_frontmatter(
        fetch, markdown, metadata, extra=settings.output.frontmatter_extra
    )
    return render_document(frontmatter, markdown)


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
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    help="Discover and count pages without downloading them (requires --all).",
)
@click.option(
    "--qmd-index",
    is_flag=True,
    help="Index the downloaded content into QMD knowledge base with LLM-generated context.",
)
@click.option(
    "--no-frontmatter",
    is_flag=True,
    help="Do not write the YAML provenance frontmatter block.",
)
@click.option(
    "--frontmatter",
    "frontmatter_extra",
    multiple=True,
    metavar="KEY: VALUE",
    help="Add a constant frontmatter field (repeatable). Example: --frontmatter 'tags: [docs]'",
)
@click.option(
    "--header",
    "extra_headers",
    multiple=True,
    metavar="NAME: VALUE",
    help="Extra HTTP header for every request (repeatable). ${ENV_VAR} is expanded. ",
)
@click.option(
    "--bearer-token-env",
    metavar="ENV_VAR",
    help="Send 'Authorization: Bearer <token>' with the token read from ENV_VAR.",
)
@click.option(
    "--basic-user",
    metavar="USERNAME",
    help="HTTP Basic username (e.g. Confluence account email). Requires --basic-token-env.",
)
@click.option(
    "--basic-token-env",
    metavar="ENV_VAR",
    help="HTTP Basic password/token read from ENV_VAR (e.g. CONFLUENCE_PAT).",
)
@click.option(
    "--allow-private-network",
    is_flag=True,
    help="Allow fetching loopback/private network addresses (bypasses the SSRF guard).",
)
@click.option(
    "--warc",
    is_flag=True,
    help="Archive raw responses to a WARC file and content-addressed store.",
)
@click.option(
    "--render",
    is_flag=True,
    help="Render pages with the configured JS renderer (sidecar binary).",
)
@click.option(
    "--chunk",
    is_flag=True,
    help="Also write a per-chunk citation manifest (.chunks.json) for each page.",
)
@click.option(
    "--sitemap",
    is_flag=True,
    help="Treat URL as a sitemap.xml: discover and list its page URLs.",
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
    dry_run: bool,
    qmd_index: bool,
    no_frontmatter: bool,
    frontmatter_extra: tuple[str, ...],
    extra_headers: tuple[str, ...],
    bearer_token_env: Optional[str],
    basic_user: Optional[str],
    basic_token_env: Optional[str],
    allow_private_network: bool,
    warc: bool,
    render: bool,
    chunk: bool,
    sitemap: bool,
):
    """
    Download websites and convert them to LLM-friendly markdown.

    URL is the website address to download and convert.

    \b
    Examples:
        gnosis https://docs.example.com/
        gnosis https://docs.example.com/ --all
        gnosis https://docs.example.com/ -o ./docs/
        gnosis https://confluence.example.com/wiki/spaces/ABC/pages/123 \\
            --basic-user me@example.com --basic-token-env CONFLUENCE_PAT
    """
    # Validate dry-run usage
    if dry_run and not crawl_all:
        console.print("[red]✗[/red] Error: --dry-run requires --all flag")
        sys.exit(1)

    # Load configuration
    settings = load_config(config)

    # Override settings from CLI options
    if output:
        settings.output.directory = str(output)
    if overwrite:
        settings.output.overwrite = True
    if allow_private_network:
        settings.downloader.allow_private_network = True
    if warc:
        settings.output.warc = True
    if render:
        settings.render.enabled = True
    if chunk:
        settings.output.chunk = True
    if qmd_index:
        settings.qmd.enabled = True
    if no_frontmatter:
        settings.output.frontmatter = False
    if frontmatter_extra:
        settings.output.frontmatter_extra.update(_parse_frontmatter_extras(frontmatter_extra))

    # Apply auth / custom headers from CLI
    _apply_cli_auth(
        settings,
        extra_headers=extra_headers,
        bearer_token_env=bearer_token_env,
        basic_user=basic_user,
        basic_token_env=basic_token_env,
    )

    if sitemap:
        for discovered in asyncio.run(_discover_sitemap(url, settings)):
            console.print(discovered)
        sys.exit(0)

    # Ensure output directory exists (unless dry-run)
    if not dry_run:
        output_dir = Path(settings.output.directory)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Run the appropriate mode
    if dry_run:
        asyncio.run(discover_pages_mode(url, settings, quiet, verbose))
    elif crawl_all:
        asyncio.run(crawl_and_convert(url, settings, quiet, verbose))
    else:
        asyncio.run(download_and_convert(url, settings, quiet, verbose))


def run_qmd_integration(
    url: str,
    output_dir: Path,
    settings: Settings,
    quiet: bool
) -> None:
    """
    Run the QMD knowledge base integration pipeline.
    
    Args:
        url: Original URL that was downloaded.
        output_dir: Directory containing the markdown files.
        settings: Configuration settings.
        quiet: Whether to suppress output.
    """
    if not settings.qmd.enabled:
        return

    # Lazy imports — torch/transformers are heavy and optional
    from gnosis.integrations.llm import LLMContextGenerator
    from gnosis.integrations.qmd import QMDCommandError, QMDIntegrator, QMDNotFoundError
    
    try:
        if not quiet:
            console.print("\n[blue]🔗[/blue] QMD Integration")
            console.print("[dim]─────────────────────[/dim]")
        
        # Initialize QMD integrator
        try:
            qmd = QMDIntegrator()
        except QMDNotFoundError as e:
            console.print(f"[yellow]⚠[/yellow] QMD not found: {e}")
            console.print("[dim]Skipping QMD integration.[/dim]")
            return
        
        # Generate collection name from URL
        collection_name = url_to_collection_name(url)
        
        if not quiet:
            console.print(f"[blue]📚[/blue] Collection: {collection_name}")
        
        # Find all markdown files
        markdown_files = sorted(output_dir.glob("**/*.md"))
        
        if not markdown_files:
            console.print("[yellow]⚠[/yellow] No markdown files found, skipping QMD integration.")
            return
        
        if not quiet:
            console.print(f"[dim]Found {len(markdown_files)} markdown file(s)[/dim]")
        
        # Generate context description using LLM
        if not quiet:
            console.print(f"[blue]🤖[/blue] Generating context with LLM ({settings.qmd.llm_model})...")
        
        try:
            llm_generator = LLMContextGenerator(settings.qmd)
            context_description = llm_generator.generate_context(
                markdown_files,
                collection_name,
                url
            )
            llm_generator.cleanup()
        except Exception as e:
            console.print(f"[red]✗[/red] LLM generation failed: {e}")
            console.print("[dim]You may need to accept the model license and login:[/dim]")
            console.print(f"[dim]  1. Visit https://huggingface.co/{settings.qmd.llm_model}[/dim]")
            console.print("[dim]  2. Run: huggingface-cli login[/dim]")
            return
        
        if not quiet:
            console.print(f"[green]✓[/green] Generated context: {context_description[:100]}...")
        
        # Run QMD pipeline
        if not quiet:
            console.print("[blue]📚[/blue] Adding collection to QMD...")
        
        try:
            qmd.run_pipeline(output_dir, collection_name, context_description)
        except QMDCommandError as e:
            console.print(f"[red]✗[/red] QMD pipeline failed: {e}")
            return
        
        if not quiet:
            console.print("[green]✅[/green] QMD integration complete!")
            console.print(f"[dim]Collection '{collection_name}' is ready for semantic search.[/dim]")
    
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠[/yellow] QMD integration interrupted")
    except Exception as e:
        console.print(f"[red]✗[/red] QMD integration error: {e}")


def _build_renderer(settings: Settings) -> Optional[ObscuraRenderer]:
    if settings.render.enabled or settings.render.auto:
        return ObscuraRenderer(binary=settings.render.engine, timeout=settings.render.timeout)
    return None


async def _maybe_render(fetch, renderer, converter, settings: Settings, quiet: bool) -> str:
    """Return HTML to convert (rendered if enabled/needed); stamp fetch provenance."""
    if renderer is None:
        return fetch.html
    should_render = settings.render.enabled
    if not should_render:
        static_md = converter.convert(fetch.html, base_url=fetch.final_url)
        should_render = len(static_md.strip()) < MIN_CONTENT_THRESHOLD
    if not should_render:
        return fetch.html
    try:
        rendered = await renderer.render(fetch.final_url)
    except RenderError as exc:
        if not quiet:
            console.print(f"[yellow]⚠[/yellow] Render failed ({exc}); using static HTML")
        return fetch.html
    fetch.render_engine = rendered.engine
    fetch.render_version = rendered.version
    fetch.render_timestamp = rendered.render_timestamp
    fetch.js_executed = rendered.js_executed
    return rendered.html


def _write_chunk_manifest(markdown: str, content_hash: str, output_path: Path, url: str) -> None:
    """Write a per-chunk citation manifest alongside a markdown file."""
    from gnosis.core.chunk import chunk_manifest, chunk_markdown

    chunks = chunk_markdown(markdown)
    manifest = chunk_manifest(url, content_hash, chunks)
    path = output_path.with_suffix(output_path.suffix + ".chunks.json")
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


async def _discover_sitemap(url: str, settings: Settings) -> list[str]:
    """Fetch a sitemap.xml and return the page URLs it lists."""
    downloader = Downloader(settings.downloader)
    try:
        return await fetch_sitemap_urls(url, downloader)
    finally:
        await downloader.close()


async def download_and_convert(url: str, settings: Settings, quiet: bool, verbose: bool) -> None:
    """Download a single page and convert to markdown."""
    downloader = Downloader(settings.downloader)
    converter = HTMLToMarkdownConverter(settings.converter, verbose=verbose)
    renderer = _build_renderer(settings)

    if not quiet:
        console.print(f"[blue]📥[/blue] Downloading: {url}")

    try:
        fetch = await downloader.fetch_result(url)
    except RobotsDisallowed as e:
        console.print(f"[yellow]⚠[/yellow] {e}")
        sys.exit(1)
    except PrivateNetworkBlocked as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to download: {e}")
        sys.exit(1)

    if settings.output.warc:
        archiver = Archiver(Path(settings.output.directory))
        try:
            archiver.archive(fetch, compute_bytes_hash(fetch.raw_bytes))
        finally:
            archiver.close()
    if not quiet:
        console.print("[blue]🔄[/blue] Converting to markdown...")

    html = await _maybe_render(fetch, renderer, converter, settings, quiet)
    metadata = converter.extract_metadata(html)
    markdown = converter.convert(html, base_url=fetch.final_url)
    document = _render_output(fetch, markdown, metadata, settings)

    # Generate output filename
    output_dir = Path(settings.output.directory)
    filename = url_to_filename(fetch.final_url) + settings.output.extension
    output_path = output_dir / filename

    # Check if file exists
    if output_path.exists() and not settings.output.overwrite:
        console.print(f"[yellow]⚠[/yellow] File exists: {output_path}")
        console.print("Use --overwrite to replace existing files.")
        sys.exit(1)

    # Save output
    output_path.write_text(document, encoding="utf-8")
    if settings.output.chunk:
        _write_chunk_manifest(markdown, compute_content_hash(markdown), output_path, fetch.final_url)

    if not quiet:
        console.print(f"[green]✓[/green] Saved: {output_path}")
        if verbose:
            console.print(f"[dim]    sha256: {compute_content_hash(markdown)[:16]}…  "
                          f"status: {fetch.status_code}  fetched: {fetch.fetched_at}[/dim]")

    # Run QMD integration if enabled
    run_qmd_integration(url, output_dir, settings, quiet)


async def discover_pages_mode(url: str, settings: Settings, quiet: bool, verbose: bool) -> None:
    """Discover and count pages without processing them."""
    downloader = Downloader(settings.downloader)
    crawler = Crawler(settings.crawler, downloader)

    if not quiet:
        console.print(f"[blue]🔍[/blue] Discovering pages under: {url}")
        console.print(
            f"    Max depth: {settings.crawler.max_depth}, "
            f"Max pages: {settings.crawler.max_pages}"
        )
        if verbose:
            console.print(
                f"    Rate limit: {settings.downloader.rate_limit_ms}ms, "
                f"Timeout: {settings.downloader.timeout}s"
            )
        console.print()

    try:
        total_count, discovered_urls, hit_max_limit = await crawler.discover_pages(url)
    except Exception as e:
        console.print(f"[red]✗[/red] Discovery failed: {e}")
        sys.exit(1)

    if not quiet:
        console.print()
        if hit_max_limit:
            console.print(
                f"[yellow]📊[/yellow] Found {total_count}+ pages "
                f"(stopped at max_pages limit of {settings.crawler.max_pages})"
            )
            console.print(
                "    [dim]Note: More pages may exist beyond this limit[/dim]"
            )
        else:
            console.print(
                f"[green]📊[/green] Found {total_count} pages "
                f"(within max_pages limit of {settings.crawler.max_pages})"
            )

        # Show URLs
        if total_count > 0:
            console.print()
            if verbose:
                # Show all discovered URLs in verbose mode
                console.print("[dim]Discovered pages:[/dim]")
                for i, page_url in enumerate(discovered_urls, 1):
                    console.print(f"  {i}. {page_url}")
            else:
                # Show sample in normal mode
                console.print("[dim]Sample pages:[/dim]")
                for i, page_url in enumerate(discovered_urls[:5], 1):
                    console.print(f"  {i}. {page_url}")
                if total_count > 5:
                    console.print(f"  ... and {total_count - 5} more")


async def crawl_and_convert(url: str, settings: Settings, quiet: bool, verbose: bool) -> None:
    """Crawl all child pages and convert each to markdown."""
    downloader = Downloader(settings.downloader)
    converter = HTMLToMarkdownConverter(settings.converter, verbose=verbose)
    crawler = Crawler(settings.crawler, downloader)
    archiver = Archiver(Path(settings.output.directory)) if settings.output.warc else None
    renderer = _build_renderer(settings)

    if not quiet:
        console.print(f"[blue]🕷[/blue] Crawling: {url}")
        console.print(
            f"    Max depth: {settings.crawler.max_depth}, "
            f"Max pages: {settings.crawler.max_pages}"
        )

    output_dir = Path(settings.output.directory)
    saved_count = 0
    skipped_count = 0
    duplicate_count = 0
    failed: list[str] = []
    llms_pages: list[dict] = []
    seen_hashes, manifest = load_checkpoint(output_dir)

    try:
        async for page_url, fetch in crawler.crawl(url):
            if not quiet:
                console.print(f"[blue]📥[/blue] Downloaded: {page_url}")
            if archiver is not None:
                archiver.archive(fetch, compute_bytes_hash(fetch.raw_bytes))

            try:
                html = await _maybe_render(fetch, renderer, converter, settings, quiet)
                metadata = converter.extract_metadata(html)
                markdown = converter.convert(html, base_url=fetch.final_url)
                if not markdown.strip():
                    raise ValueError("conversion produced empty output")
                content_hash = compute_content_hash(markdown)
                if content_hash in seen_hashes:
                    duplicate_count += 1
                    if not quiet:
                        console.print(f"[dim]⏭  Skipped (duplicate): {page_url}[/dim]")
                    continue
                seen_hashes.add(content_hash)
                document = _render_output(fetch, markdown, metadata, settings)
            except Exception as e:
                if not quiet:
                    console.print(f"[red]✗[/red] Failed to convert {page_url}: {e}")
                failed.append(page_url)
                continue

            filename = url_to_filename(page_url, base_url=url) + settings.output.extension
            output_path = output_dir / filename

            if output_path.exists() and not settings.output.overwrite:
                if not quiet:
                    console.print(f"[yellow]⚠[/yellow] Skipped (exists): {output_path}")
                skipped_count += 1
                continue

            output_path.write_text(document, encoding="utf-8")
            if settings.output.chunk:
                _write_chunk_manifest(markdown, compute_content_hash(markdown), output_path, page_url)
            saved_count += 1
            llms_pages.append({"url": page_url, "title": metadata.get("title") or page_url, "markdown": markdown})
            manifest.append(
                {
                    "url": page_url,
                    "file": filename,
                    "content_hash": content_hash,
                    "fetched_at": fetch.fetched_at,
                    "status_code": fetch.status_code,
                    "title": metadata.get("title") or "",
                }
            )
            save_checkpoint(output_dir, seen_hashes, manifest)

            if not quiet:
                console.print(f"[green]✓[/green] Saved: {output_path}")
    finally:
        if archiver is not None:
            archiver.close()

    # Write crawl manifest for auditing / downstream bookkeeping
    if manifest:
        manifest_path = output_dir / "_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if not quiet:
            console.print(f"[dim]📋 Manifest: {manifest_path}[/dim]")

    if llms_pages:
        site_name = urlparse(url).netloc or url
        (output_dir / "llms.txt").write_text(render_llms_txt(site_name, llms_pages), encoding="utf-8")
        (output_dir / "llms-full.txt").write_text(render_llms_full(llms_pages), encoding="utf-8")
        if not quiet:
            console.print("[dim]📄 llms.txt + llms-full.txt written[/dim]")
    if not quiet:
        console.print()
        console.print("[green]✅[/green] Complete!")
        console.print(f"    Saved: {saved_count} files")
        if skipped_count > 0:
            console.print(f"    Skipped: {skipped_count} files (already exist)")
        if duplicate_count > 0:
            console.print(f"    [dim]Skipped: {duplicate_count} duplicates (same content)[/dim]")
        if failed:
            console.print(f"    [red]Failed: {len(failed)} pages[/red]")

    # Run QMD integration if enabled
    run_qmd_integration(url, output_dir, settings, quiet)

    # Meaningful exit codes for schedulers: 0 = at least one page saved,
    # 1 = nothing saved at all.
    if saved_count == 0 and skipped_count == 0:
        sys.exit(1)


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
