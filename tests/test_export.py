"""Tests for multi-format export."""

import json

import pytest

from gnosis.core.export import export_records

RECORDS = [
    {
        "url": "https://x/a",
        "markdown": "# A",
        "content_hash": "a" * 64,
        "bytes_sha256": "b" * 64,
        "status_code": 200,
    }
]


def test_export_json(tmp_path):
    path = export_records(RECORDS, tmp_path, "json")
    data = json.loads(path.read_text())
    assert data[0]["url"] == "https://x/a"
    assert data[0]["content_hash"] == "a" * 64
    assert data[0]["markdown"] == "# A"


def test_export_jsonl(tmp_path):
    path = export_records(RECORDS, tmp_path, "jsonl")
    lines = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0]["bytes_sha256"] == "b" * 64


def test_export_parquet_roundtrip(tmp_path):
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    path = export_records(RECORDS, tmp_path, "parquet")
    rows = pq.read_table(path).to_pylist()
    assert rows[0]["url"] == "https://x/a"
    assert rows[0]["content_hash"] == "a" * 64


def test_unsupported_format_raises(tmp_path):
    with pytest.raises(ValueError):
        export_records(RECORDS, tmp_path, "csv")
