"""Optional document conversion (PDF/Office/image → Markdown).

MarkItDown is a heavy optional dependency, imported lazily so the core
gnosis install never pulls it in. Install with:

    pip install gnosis-markdown[docs]
"""

from pathlib import Path

import click
from rich.console import Console

console = Console()


class MarkItDownDocumentConverter:
    """Convert documents via the `markitdown` package (lazy import)."""

    def convert(self, path: str | Path) -> str:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise ImportError(
                "markitdown is not installed. Install it with: "
                "pip install gnosis-markdown[docs]"
            ) from exc

        result = MarkItDown().convert(str(path))
        return result.text_content


def convert_document(path: str | Path) -> str:
    """Convert a document (PDF/DOCX/XLSX/PPTX/image/...) to Markdown."""
    return MarkItDownDocumentConverter().convert(path)


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output .md path.")
def main(path: Path, output: Path | None) -> None:
    """Convert a document (PDF/Office/image) to Markdown."""
    try:
        markdown = convert_document(path)
    except ImportError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise SystemExit(1) from exc

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        console.print(f"[green]✓[/green] Saved: {output}")
    else:
        console.print(markdown)


if __name__ == "__main__":
    main()
