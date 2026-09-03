"""Tests for the compliance policy engine."""

from gnosis.core.policy import PolicyEngine


def test_deny_by_license():
    engine = PolicyEngine(
        [{"name": "no-proprietary", "deny_if": {"license": ["All Rights Reserved"]}, "reason": "proprietary"}]
    )
    d = engine.evaluate("https://x/a", {"license": "All Rights Reserved"})
    assert not d.allowed
    assert d.rule == "no-proprietary"
    assert d.reason == "proprietary"


def test_deny_by_ai_txt():
    engine = PolicyEngine([{"name": "no-training", "deny_if": {"ai_txt": {"training": "Deny"}}}])
    d = engine.evaluate("https://x/a", {"ai_txt": {"training": "Deny"}})
    assert not d.allowed
    assert d.rule == "no-training"


def test_deny_by_path():
    engine = PolicyEngine([{"name": "no-admin", "deny_if": {"path": ["/admin/*"]}}])
    assert not engine.evaluate("https://x/admin/users", {}).allowed
    assert engine.evaluate("https://x/docs", {}).allowed


def test_deny_overrides_allow():
    """Deny-overrides: a matching allow path must NOT override an explicit opt-out."""
    engine = PolicyEngine(
        [
            {"name": "allow-docs", "allow_if": {"path": ["/docs/*"]}},
            {"name": "deny-training", "deny_if": {"ai_txt": {"training": "Deny"}}, "reason": "no training"},
        ]
    )
    d = engine.evaluate("https://x/docs/a", {"ai_txt": {"training": "Deny"}})
    assert not d.allowed
    assert d.rule == "deny-training"


def test_no_rules_allows():
    engine = PolicyEngine([])
    assert engine.evaluate("https://x/a", {}).allowed


def test_license_match_is_substring_case_insensitive():
    engine = PolicyEngine([{"name": "no-cc", "deny_if": {"license": ["cc-by-nc"]}}])
    assert not engine.evaluate("https://x/a", {"license": "CC-BY-NC 4.0"}).allowed


def test_scalar_license_normalized():
    """Regression (reviewer P2): a scalar license pattern must not be iterated char-by-char."""
    engine = PolicyEngine([{"name": "no-cc", "deny_if": {"license": "CC-BY-NC"}}])
    assert not engine.evaluate("https://x/a", {"license": "CC-BY-NC 4.0"}).allowed
    assert engine.evaluate("https://x/a", {"license": "MIT"}).allowed


def test_malformed_rule_raises():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        PolicyEngine(["not-a-dict"])
