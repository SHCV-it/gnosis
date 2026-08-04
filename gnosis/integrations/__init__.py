"""
Integration modules for external tools and services.

Imports are lazy — heavy dependencies (torch, transformers) required only
by the QMD integration are not loaded until --qmd-index is used. Install
the [qmd] extra to enable: pip install gnosis-markdown[qmd]
"""

__all__: list[str] = []
