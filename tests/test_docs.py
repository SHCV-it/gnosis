"""Regression tests: the docs' example artifacts stay in sync with the package version.

Rationale: the README/docs show a `generator: gnosis/X.Y.Z` provenance block. If that
drifts behind `gnosis.__version__`, the flagship "auditable" example is self-inconsistent
— exactly the kind of drift the product's own thesis says it must not ship.
"""

import re
from pathlib import Path

from gnosis import __version__

ROOT = Path(__file__).resolve().parents[1]

_ALL_DOCS = [
    "README.md",
    "docs/provenance.md",
    "docs/index.md",
    "docs/capture-record-spec.md",
]

_GENERATOR_RE = re.compile(r"generator:\s*gnosis/(\d+\.\d+\.\d+)")


def test_readme_generator_matches_version():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"generator: gnosis/{__version__}" in text


def test_provenance_doc_generator_matches_version():
    text = (ROOT / "docs/provenance.md").read_text(encoding="utf-8")
    assert f"generator: gnosis/{__version__}" in text


def test_no_stale_generator_version_in_docs():
    for rel in _ALL_DOCS:
        for m in _GENERATOR_RE.finditer((ROOT / rel).read_text(encoding="utf-8")):
            assert m.group(1) == __version__, f"{rel}: stale {m.group(0)}"
