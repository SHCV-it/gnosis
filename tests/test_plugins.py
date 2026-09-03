"""Tests for the plugin/hook system."""

import pytest

from gnosis.core.plugins import PluginManager


def _plugin(tmp_path, source):
    path = tmp_path / "plug.py"
    path.write_text(source)
    return str(path)


def test_post_process_hook(tmp_path):
    path = _plugin(tmp_path, "def post_process(markdown, metadata):\n    return markdown + '\\n<!-- plugin -->'\n")
    mgr = PluginManager([path])
    assert mgr.post_process("# Hi", {}) == "# Hi\n<!-- plugin -->"


def test_pre_fetch_hook(tmp_path):
    path = _plugin(
        tmp_path,
        "def pre_fetch(url, headers):\n    return url + '?x=1', {**headers, 'X-Plugin': '1'}\n",
    )
    mgr = PluginManager([path])
    url, headers = mgr.pre_fetch("http://a", {})
    assert url == "http://a?x=1"
    assert headers["X-Plugin"] == "1"


def test_post_fetch_hook(tmp_path):
    path = _plugin(tmp_path, "def post_fetch(fetch):\n    fetch.plugin_seen = True\n")
    mgr = PluginManager([path])

    class Fetch:
        pass

    fetch = Fetch()
    mgr.post_fetch(fetch)
    assert fetch.plugin_seen is True


def test_hooks_apply_in_order(tmp_path):
    p1 = tmp_path / "p1.py"
    p1.write_text("def post_process(markdown, metadata):\n    return markdown + 'A'\n")
    p2 = tmp_path / "p2.py"
    p2.write_text("def post_process(markdown, metadata):\n    return markdown + 'B'\n")
    mgr = PluginManager([str(p1), str(p2)])
    assert mgr.post_process("", {}) == "AB"


def test_missing_plugin_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        PluginManager([str(tmp_path / "nope.py")])


def test_pre_fetch_receives_effective_headers(tmp_path):
    """Regression (#63): pre_fetch must see the effective request headers, not {}."""
    from gnosis.core.plugins import PluginManager

    plug = tmp_path / "plug.py"
    plug.write_text(
        "def pre_fetch(url, headers):\n"
        "    headers['X-Saw-UA'] = headers.get('User-Agent', '')\n"
        "    return url, headers\n"
    )
    mgr = PluginManager([str(plug)])
    url, headers = mgr.pre_fetch("http://a", {"User-Agent": "Gnosis/2.0"})
    assert headers["X-Saw-UA"] == "Gnosis/2.0"
