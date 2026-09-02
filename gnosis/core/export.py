"""Multi-format export of captured documents (JSON / JSONL / Parquet).

Every exported record carries its provenance fields (url, content_hash,
bytes_sha256, status_code, fetched_at, ...) plus the markdown body. Parquet
imports pyarrow lazily so it stays an optional extra
(`pip install 'gnosis-markdown[parquet]'`).
"""

from __future__ import annotations

import json
from pathlib import Path

SUPPORTED_FORMATS = ("json", "jsonl", "parquet")


def export_records(records: list[dict], output_dir: Path, fmt: str) -> Path:
    """Write records to documents.<fmt>; return the written path."""
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported export format: {fmt!r}")

    output_dir = Path(output_dir)
    if fmt == "json":
        path = output_dir / "documents.json"
        path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    elif fmt == "jsonl":
        path = output_dir / "documents.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
    else:  # parquet
        path = output_dir / "documents.parquet"
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - exercised via [parquet] extra
            raise ImportError(
                "Parquet export requires 'pyarrow'. "
                "Install it with: pip install 'gnosis-markdown[parquet]'"
            ) from exc
        table = pa.Table.from_pylist(records)
        pq.write_table(table, path)

    return path
