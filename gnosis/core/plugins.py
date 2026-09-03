"""Plugin/hook system: pre_fetch / post_fetch / post_process.

Plugins are Python files loaded by path (config `plugins:` list). A plugin
module may define any of three optional hooks:

- `pre_fetch(url, headers) -> (url, headers)` — rewrite the URL / add headers
  before the request.
- `post_fetch(fetch)` — inspect or mutate the FetchResult after download.
- `post_process(markdown, metadata) -> markdown` — transform the converted
  Markdown (custom cleaning, redaction, enrichment).

Hooks are applied in plugin order. Missing hooks are skipped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


class PluginManager:
    """Load plugin modules from file paths and apply their hooks."""

    def __init__(self, plugin_paths: list[str] | None = None):
        self.plugins = [self._load(Path(p)) for p in (plugin_paths or [])]

    @staticmethod
    def _load(path: Path):
        if not path.exists():
            raise FileNotFoundError(f"plugin not found: {path}")
        name = f"gnosis_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load plugin: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def pre_fetch(self, url: str, headers: dict) -> tuple[str, dict]:
        for plugin in self.plugins:
            hook = getattr(plugin, "pre_fetch", None)
            if callable(hook):
                result = hook(url, headers)
                if result is not None:
                    url, headers = result
        return url, headers

    def post_fetch(self, fetch) -> None:
        for plugin in self.plugins:
            hook = getattr(plugin, "post_fetch", None)
            if callable(hook):
                hook(fetch)

    def post_process(self, markdown: str, metadata: dict) -> str:
        for plugin in self.plugins:
            hook = getattr(plugin, "post_process", None)
            if callable(hook):
                result = hook(markdown, metadata)
                if result is not None:
                    markdown = result
        return markdown
