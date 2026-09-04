"""
Configuration settings loader for Gnosis.

Loads settings from YAML files with defaults and validation.
Secret values (tokens, passwords) are never stored in config files:
use ${ENV_VAR} references, which are expanded at load time.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value):
    """
    Expand ${ENV_VAR} references in a string (or recursively in lists/dicts).

    Missing variables expand to an empty string so misconfiguration fails
    loudly at request time (HTTP 401) rather than silently sending nothing.

    Args:
        value: String, list, dict, or other scalar.

    Returns:
        Value with environment variable references expanded.
    """
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


@dataclass
class AuthSettings:
    """
    Authentication settings for the downloader.

    Exactly one scheme is used:
      - bearer: Authorization: Bearer <token>
      - basic:  HTTP Basic with username/password (Confluence Cloud PAT:
                username = account email, password = API token)
      - header: arbitrary single header (name/value)
    """

    type: str = ""  # "bearer" | "basic" | "header" | ""
    token: str = ""
    username: str = ""
    password: str = ""
    name: str = ""
    value: str = ""

    def headers(self) -> dict[str, str]:
        """Return the HTTP headers implied by this auth config."""
        if self.type == "bearer" and self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.type == "basic" and self.username:
            import base64

            raw = f"{self.username}:{self.password}".encode()
            return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}
        if self.type == "header" and self.name:
            return {self.name: self.value}
        return {}


@dataclass
class DownloaderSettings:
    """Settings for the HTTP downloader."""

    timeout: int = 30
    retries: int = 3
    user_agent: str = "Gnosis/2.2 (auditable website-to-markdown converter)"
    rate_limit_ms: int = 500
    respect_robots: bool = True
    allow_private_network: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    auth: Optional[AuthSettings] = None

    def request_headers(self) -> dict[str, str]:
        """Effective request headers: custom headers overlaid with auth."""
        merged = dict(self.headers)
        if self.auth:
            merged.update(self.auth.headers())
        return merged


@dataclass
class CrawlerSettings:
    """Settings for the website crawler."""

    max_depth: int = 10
    max_pages: int = 500
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
            "select",
            "textarea",
            "meta",
            "link",
            "head",
            "template",
        ]
    )
    # Tried in order; the first selector with a substantial match wins.
    # Platform-specific containers come first so generic landmarks
    # ('main', '#content') don't win when they wrap nav chrome.
    content_selectors: list[str] = field(
        default_factory=lambda: [
            ".markdown-body",  # GitHub / GitLab rendered markdown
            ".ak-renderer-document",  # Confluence Cloud page body
            ".wiki-content",  # Confluence Server/Data Center page body
            ".docs-content",
            ".documentation",
            "main",
            "article",
            '[role="main"]',
            ".prose",
            ".content",
            "#content",
            "#main",
        ]
    )
    # Exact class-token matches to strip (backward-compatible behavior).
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
    # Word-level matches: a class token is split on '-' and '_' into words;
    # if any word matches an entry here, the element is stripped.
    # Catches namespaced boilerplate like 'bd-sidebar-primary' or
    # 'site-breadcrumbs' without false-positives like 'research-content'.
    strip_class_words: list[str] = field(
        default_factory=lambda: [
            "sidebar",
            "toc",
            "breadcrumb",
            "breadcrumbs",
            "pagination",
            "pager",
            "sourcelink",
            "headerlink",
            "prevnext",
            "cookie",
            "consent",
            "newsletter",
            "subscribe",
            "social",
            "share",
            "feedback",
            "badge",
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
    # Write a YAML frontmatter block with provenance metadata by default.
    frontmatter: bool = True
    # Extra constant frontmatter fields (e.g. tags, owner, reliability).
    # Values support ${ENV_VAR} expansion.
    frontmatter_extra: dict[str, object] = field(default_factory=dict)
    warc: bool = False
    chunk: bool = False


@dataclass
class QMDSettings:
    """Settings for QMD knowledge base integration."""

    enabled: bool = False
    llm_model: str = "Qwen/Qwen3-0.6B"
    llm_device: str = "cpu"
    llm_dtype: str = "float32"
    context_prompt_template: str = (
        "What is this documentation about? Reply with one concise sentence only."
        " Do not repeat the title, do not use markdown, do not use headings."
        "\n\n{content}"
    )
    max_tokens: int = 80
    temperature: float = 0.3
    top_k: int = 50
    top_p: float = 0.95
    sample_files_limit: int = 5
    sample_content_max_chars: int = 10000


@dataclass
class RenderSettings:
    """Settings for the optional JS renderer."""

    enabled: bool = False
    auto: bool = False
    engine: str = "obscura"
    timeout: float = 30.0


@dataclass
class Settings:
    """Main settings container for Gnosis."""

    downloader: DownloaderSettings = field(default_factory=DownloaderSettings)
    crawler: CrawlerSettings = field(default_factory=CrawlerSettings)
    converter: ConverterSettings = field(default_factory=ConverterSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    qmd: QMDSettings = field(default_factory=QMDSettings)
    render: RenderSettings = field(default_factory=RenderSettings)
    policies: list = field(default_factory=list)
    plugins: list = field(default_factory=list)


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

    # Expand ${ENV_VAR} references throughout the config (secrets stay in env)
    data = expand_env(data)

    # Load downloader settings
    if "downloader" in data:
        dl = data["downloader"]
        auth_data = dl.get("auth") or {}
        auth = None
        if auth_data.get("type"):
            auth = AuthSettings(
                type=auth_data.get("type", ""),
                token=auth_data.get("token", ""),
                username=auth_data.get("username", ""),
                password=auth_data.get("password", ""),
                name=auth_data.get("name", ""),
                value=auth_data.get("value", ""),
            )
        settings.downloader = DownloaderSettings(
            timeout=dl.get("timeout", settings.downloader.timeout),
            retries=dl.get("retries", settings.downloader.retries),
            user_agent=dl.get("user_agent", settings.downloader.user_agent),
            rate_limit_ms=dl.get("rate_limit_ms", settings.downloader.rate_limit_ms),
            respect_robots=dl.get("respect_robots", settings.downloader.respect_robots),
            allow_private_network=dl.get("allow_private_network", settings.downloader.allow_private_network),
            headers=dict(dl.get("headers") or {}),
            auth=auth,
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
            strip_class_words=cv.get(
                "strip_class_words", settings.converter.strip_class_words
            ),
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
            frontmatter=out.get("frontmatter", settings.output.frontmatter),
            warc=out.get("warc", settings.output.warc),
            chunk=out.get("chunk", settings.output.chunk),
            frontmatter_extra=dict(
                out.get("frontmatter_extra") or settings.output.frontmatter_extra
            ),
        )

    # Load QMD settings
    if "qmd" in data:
        qmd = data["qmd"]
        settings.qmd = QMDSettings(
            enabled=qmd.get("enabled", settings.qmd.enabled),
            llm_model=qmd.get("llm_model", settings.qmd.llm_model),
            llm_device=qmd.get("llm_device", settings.qmd.llm_device),
            llm_dtype=qmd.get("llm_dtype", settings.qmd.llm_dtype),
            context_prompt_template=qmd.get(
                "context_prompt_template", settings.qmd.context_prompt_template
            ),
            max_tokens=qmd.get("max_tokens", settings.qmd.max_tokens),
            temperature=qmd.get("temperature", settings.qmd.temperature),
            top_k=qmd.get("top_k", settings.qmd.top_k),
            top_p=qmd.get("top_p", settings.qmd.top_p),
            sample_files_limit=qmd.get("sample_files_limit", settings.qmd.sample_files_limit),
            sample_content_max_chars=qmd.get(
                "sample_content_max_chars", settings.qmd.sample_content_max_chars
            ),
        )

    if "render" in data:
        rd = data["render"]
        settings.render = RenderSettings(
            enabled=rd.get("enabled", settings.render.enabled),
            auto=rd.get("auto", settings.render.auto),
            engine=rd.get("engine", settings.render.engine),
            timeout=rd.get("timeout", settings.render.timeout),
        )

    settings.policies = data.get("policies") or []
    _plugins = data.get("plugins") or []
    settings.plugins = [
        str((config_path.parent / pp).resolve()) if not Path(pp).is_absolute() else pp
        for pp in _plugins
    ]
    return settings


def get_default_config_path() -> Path:
    """Get path to the default config file shipped with the package."""
    return Path(__file__).parent / "default.yaml"
