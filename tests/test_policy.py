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


def test_allow_precedes_deny():
    engine = PolicyEngine(
        [
            {"name": "deny-cc", "deny_if": {"license": ["CC-BY"]}, "reason": "x"},
            {"name": "allow-cc", "allow_if": {"license": ["CC-BY"]}},
        ]
    )
    d = engine.evaluate("https://x/a", {"license": "CC-BY 4.0"})
    assert d.allowed
    assert d.rule == "allow-cc"


def test_no_rules_allows():
    engine = PolicyEngine([])
    assert engine.evaluate("https://x/a", {}).allowed


def test_license_match_is_substring_case_insensitive():
    engine = PolicyEngine([{"name": "no-cc", "deny_if": {"license": ["cc-by-nc"]}}])
    assert not engine.evaluate("https://x/a", {"license": "CC-BY-NC 4.0"}).allowed
