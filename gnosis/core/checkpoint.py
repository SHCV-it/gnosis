"""Resumable-crawl checkpoint persistence.

Persists the crawl's dedup state (seen content hashes) and the running
manifest, so an interrupted `--all` crawl can resume: already-captured
content is not re-saved, and the manifest/llms.txt accumulate across runs.
"""

import json
from pathlib import Path

CHECKPOINT_FILENAME = ".gnosis-checkpoint.json"


def save_checkpoint(output_dir: Path, seen_hashes: set[str], manifest: list[dict]) -> None:
    data = {"seen_hashes": sorted(seen_hashes), "manifest": manifest}
    (output_dir / CHECKPOINT_FILENAME).write_text(json.dumps(data), encoding="utf-8")


def load_checkpoint(output_dir: Path) -> tuple[set[str], list[dict]]:
    path = output_dir / CHECKPOINT_FILENAME
    if not path.exists():
        return set(), []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set(), []
    return set(data.get("seen_hashes", [])), data.get("manifest", [])
