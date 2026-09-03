"""Tests for named compliance policy profiles."""

import pytest

from gnosis.config.profiles import PROFILES, get_profile
from gnosis.core.policy import PolicyEngine


def test_all_profiles_parse():
    for name, rules in PROFILES.items():
        # must construct without raising (rule schema is valid)
        PolicyEngine(rules)


def test_get_profile_default_empty():
    assert get_profile("default") == []


def test_compliance_denies_proprietary_license():
    engine = PolicyEngine(get_profile("compliance"))
    assert not engine.evaluate("https://x/a", {"license": "All Rights Reserved"}).allowed


def test_compliance_denies_training_denied():
    engine = PolicyEngine(get_profile("compliance"))
    assert not engine.evaluate("https://x/a", {"ai_txt": {"training": "Deny"}}).allowed


def test_open_only_denies_noncommercial():
    engine = PolicyEngine(get_profile("open-only"))
    assert not engine.evaluate("https://x/a", {"license": "CC-BY-NC 4.0"}).allowed
    assert engine.evaluate("https://x/a", {"license": "CC-BY 4.0"}).allowed


def test_open_only_denies_canonical_cc_encodings():
    """Regression (reviewer P1): NC/ND must be denied in spaced + URL encodings,
    not only the hyphenated cc-by-nc token."""
    engine = PolicyEngine(get_profile("open-only"))
    assert not engine.evaluate("https://x/a", {"license": "CC BY-NC 4.0"}).allowed
    assert not engine.evaluate(
        "https://x/a", {"license": "https://creativecommons.org/licenses/by-nc/4.0/"}
    ).allowed
    assert not engine.evaluate("https://x/a", {"license": "CC BY-ND 4.0"}).allowed
    assert engine.evaluate("https://x/a", {"license": "CC BY 4.0"}).allowed


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        get_profile("nope")
