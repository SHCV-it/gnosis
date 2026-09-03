"""Named compliance policy presets for the `--profile` CLI flag."""

from __future__ import annotations

# Each profile is an ordered list of PolicyEngine rules (see gnosis/core/policy.py).
PROFILES: dict[str, list[dict]] = {
    "default": [],
    "compliance": [
        {
            "name": "no-training-denied",
            "deny_if": {"ai_txt": {"training": "Deny"}},
            "reason": "site prohibits AI training",
        },
        {
            "name": "no-proprietary",
            "deny_if": {"license": ["All Rights Reserved"]},
            "reason": "proprietary content",
        },
    ],
    "open-only": [
        {
            "name": "open-licenses-only",
            "deny_if": {"license": ["All Rights Reserved", "proprietary", "by-nc", "by-nd"]},
            "reason": "license is not permissive/open",
        },
    ],
}


def get_profile(name: str) -> list[dict]:
    """Return a copy of the policy list for a named profile."""
    if name not in PROFILES:
        raise ValueError(f"unknown profile: {name!r} (available: {', '.join(PROFILES)})")
    import copy

    return copy.deepcopy(PROFILES[name])
