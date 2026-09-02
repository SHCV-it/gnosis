"""Tests for resumable-crawl checkpoint persistence."""

from gnosis.core.checkpoint import CHECKPOINT_FILENAME, load_checkpoint, save_checkpoint


def test_roundtrip(tmp_path):
    save_checkpoint(tmp_path, {"a", "b"}, [{"url": "x"}])
    seen, manifest = load_checkpoint(tmp_path)
    assert seen == {"a", "b"}
    assert manifest == [{"url": "x"}]


def test_load_missing_returns_empty(tmp_path):
    seen, manifest = load_checkpoint(tmp_path)
    assert seen == set()
    assert manifest == []


def test_load_corrupt_returns_empty(tmp_path):
    (tmp_path / CHECKPOINT_FILENAME).write_text("{not json")
    seen, manifest = load_checkpoint(tmp_path)
    assert seen == set()
    assert manifest == []
