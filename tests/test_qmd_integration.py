"""Tests for the QMD integration (subprocess-bound; no qmd binary needed)."""

import pathlib

import pytest

from gnosis.integrations.qmd import QMDCommandError, QMDIntegrator, QMDNotFoundError


def test_parse_existing_collection_name():
    assert QMDIntegrator._parse_existing_collection_name("Error: Name: my-collection") == "my-collection"
    assert QMDIntegrator._parse_existing_collection_name("garbage") is None


def test_init_raises_when_binary_missing(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(QMDNotFoundError):
        QMDIntegrator()


def _proc(rc, stdout="", stderr=""):
    import types

    return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def test_add_collection_command(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "gnosis.integrations.qmd.subprocess.run", lambda cmd, **kw: calls.append(cmd) or _proc(0)
    )
    q = QMDIntegrator(qmd_binary="qmd")
    assert q.add_collection(pathlib.Path("/tmp/out"), "col") is True
    assert calls[0][:3] == ["qmd", "collection", "add"]


def test_already_exists_retry(monkeypatch):
    calls = []
    state = {"n": 0}

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if state["n"] == 0:
            state["n"] += 1
            return _proc(1, "Error: already exists Name: old-col")
        return _proc(0)

    monkeypatch.setattr("gnosis.integrations.qmd.subprocess.run", fake_run)
    q = QMDIntegrator(qmd_binary="qmd")
    assert q.add_collection(pathlib.Path("/tmp/out"), "col") is True
    cmds = [c[:3] for c in calls]
    assert ["qmd", "collection", "add"] in cmds
    assert ["qmd", "collection", "remove"] in cmds


def test_pipeline_order(monkeypatch):
    order = []

    def fake_run(cmd, **kw):
        order.append(cmd[1])
        return _proc(0)

    monkeypatch.setattr("gnosis.integrations.qmd.subprocess.run", fake_run)
    q = QMDIntegrator(qmd_binary="qmd")
    q.run_pipeline(pathlib.Path("/tmp/out"), "col", "desc")
    assert order == ["collection", "context", "embed"]


def test_command_error_on_failure(monkeypatch):
    monkeypatch.setattr(
        "gnosis.integrations.qmd.subprocess.run",
        lambda cmd, **kw: _proc(1, "", "boom"),
    )
    q = QMDIntegrator(qmd_binary="qmd")
    with pytest.raises(QMDCommandError):
        q.add_collection(pathlib.Path("/tmp/out"), "col")
