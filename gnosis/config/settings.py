"""
Configuration settings loader for Gnosis.

Loads settings from YAML files with defaults and validation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class DownloaderSettings:
    """Settings for the HTTP downloader."""

    timeout: int = 30
    retries: int = 3
    user_agent: str = "Gnosis/1.0 (Website to Markdown converter)"
    rate_limit_ms: int = 500
    respect_robots: bool = True


@dataclass
class CrawlerSettings:
    """Settings for the website crawler."""

    max_depth: int = 10
    max_pages: int = 100
    concurrent_requests: int = 5


@dataclass
class ConverterSettings:
    """Settings for the HTML to Markdown converter."""

    excluded_tags: list[str] = field(
        default_factory=lambda: [
            "script",
            "style",
            "noscript",
            "nav",
            "footer",
            "aside",
            "svg",
            "canvas",
            "iframe",
            "button",
            "input",
            "form",
            "meta",
            "link",
            "head",
        ]
    )
    content_selectors: list[str] = field(
        default_factory=lambda: [
            "main",
            "article",
            '[role="main"]',
            ".content",
            ".documentation",
            ".docs-content",
            ".markdown-body",
            ".prose",
            "#content",
            "#main",
        ]
    )
    strip_classes: list[str] = field(
        default_factory=lambda: [
            "sidebar",
            "menu",
            "toc",
            "table-of-contents",
            "navigation",
            "breadcrumb",
            "pagination",
            "search",
            "header",
            "footer",
        ]
    )
    include_images: bool = True
    absolute_urls: bool = True


@dataclass
class OutputSettings:
    """Settings for output files."""

    directory: str = "./"
    overwrite: bool = False
    extension: str = ".md"


@dataclass
class Settings:
    """Main settings container for Gnosis."""

    downloader: DownloaderSettings = field(default_factory=DownloaderSettings)
    crawler: CrawlerSettings = field(default_factory=CrawlerSettings)
    converter: ConverterSettings = field(default_factory=ConverterSettings)
    output: OutputSettings = field(default_factory=OutputSettings)


def load_config(config_path: Optional[Path] = None) -> Settings:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to YAML config file. If None, uses defaults.

    Returns:
        Settings object with loaded configuration.
    """
    settings = Settings()

    if config_path is None:
        return settings

    config_path = Path(config_path)
    if not config_path.exists():
        return settings

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    # Load downloader settings
    if "downloader" in data:
        dl = data["downloader"]
        settings.downloader = DownloaderSettings(
            timeout=dl.get("timeout", settings.downloader.timeout),
            retries=dl.get("retries", settings.downloader.retries),
            user_agent=dl.get("user_agent", settings.downloader.user_agent),
            rate_limit_ms=dl.get("rate_limit_ms", settings.downloader.rate_limit_ms),
            respect_robots=dl.get("respect_robots", settings.downloader.respect_robots),
        )

    # Load crawler settings
    if "crawler" in data:
        cr = data["crawler"]
        settings.crawler = CrawlerSettings(
            max_depth=cr.get("max_depth", settings.crawler.max_depth),
            max_pages=cr.get("max_pages", settings.crawler.max_pages),
            concurrent_requests=cr.get(
                "concurrent_requests", settings.crawler.concurrent_requests
            ),
        )

    # Load converter settings
    if "converter" in data:
        cv = data["converter"]
        settings.converter = ConverterSettings(
            excluded_tags=cv.get("excluded_tags", settings.converter.excluded_tags),
            content_selectors=cv.get(
                "content_selectors", settings.converter.content_selectors
            ),
            strip_classes=cv.get("strip_classes", settings.converter.strip_classes),
            include_images=cv.get("include_images", settings.converter.include_images),
            absolute_urls=cv.get("absolute_urls", settings.converter.absolute_urls),
        )

    # Load output settings
    if "output" in data:
        out = data["output"]
        settings.output = OutputSettings(
            directory=out.get("directory", settings.output.directory),
            overwrite=out.get("overwrite", settings.output.overwrite),
            extension=out.get("extension", settings.output.extension),
        )

    return settings


def get_default_config_path() -> Path:
    """Get path to the default config file shipped with the package."""
    return Path(__file__).parent.parent.parent / "config" / "default.yaml"
