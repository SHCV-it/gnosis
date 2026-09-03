"""Tests for resumable-crawl checkpoint persistence."""

from gnosis.core.checkpoint import CHECKPOINT_FILENAME, load_checkpoint, save_checkpoint


def test_roundtrip(tmp_path):
    save_checkpoint(tmp_path, {"a", "b"}, [{"url": "x"}])
    seen, manifest, _f, _v = load_checkpoint(tmp_path)
    assert seen == {"a", "b"}
    assert manifest == [{"url": "x"}]


def test_load_missing_returns_empty(tmp_path):
    seen, manifest, _f, _v = load_checkpoint(tmp_path)
    assert seen == set()
    assert manifest == []


def test_load_corrupt_returns_empty(tmp_path):
    (tmp_path / CHECKPOINT_FILENAME).write_text("{not json")
    seen, manifest, _f, _v = load_checkpoint(tmp_path)
    assert seen == set()
    assert manifest == []


def test_save_is_atomic_no_tmp_left(tmp_path):
    """Regression (#44): save_checkpoint writes via temp+rename; no .tmp file
    remains and the checkpoint round-trips."""
    from gnosis.core.checkpoint import CHECKPOINT_FILENAME, load_checkpoint, save_checkpoint

    save_checkpoint(tmp_path, {"a", "b"}, [{"url": "https://x"}])
    assert not (tmp_path / (CHECKPOINT_FILENAME + ".tmp")).exists()
    hashes, manifest, _f, _v = load_checkpoint(tmp_path)
    assert hashes == {"a", "b"}
    assert manifest == [{"url": "https://x"}]
