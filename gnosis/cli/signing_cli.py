"""CLI subcommands for signing and verifying gnosis documents."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from gnosis.core.signing import generate_keypair, verify_document

console = Console()


@click.command("keygen")
def keygen():
    """Generate an Ed25519 keypair and print it (public + private)."""
    private_pem, public_b64 = generate_keypair()
    console.print("[bold green]Public key (base64):[/bold green]")
    console.print(public_b64)
    console.print()
    console.print("[bold yellow]Private key (PEM) — keep secret:[/bold yellow]")
    console.print(private_pem, end="")


@click.command("verify")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def verify(path: Path):
    """Verify the Ed25519 signature on a gnosis markdown file."""
    document = path.read_text(encoding="utf-8")
    ok, reason = verify_document(document)
    if ok:
        console.print(f"[green]✓[/green] {reason}")
        sys.exit(0)
    console.print(f"[red]✗[/red] {reason}")
    sys.exit(1)
