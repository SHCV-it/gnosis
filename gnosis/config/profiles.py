"""Named compliance policy presets for the `--profile` CLI flag.

Each profile is a list of PolicyEngine rules. The names are chosen to be honest
about what they actually enforce (literal matching, deny-overrides):

- `default` — no policies.
- `strict-optout` — blocks sites whose ai.txt says training/data is denied
  (normalised: Deny/Disallow/no/opt-out), whose ai.txt `Disallow:` path covers
  the page, or whose `license` field contains "All Rights Reserved". It does
  NOT attempt full license classification — it matches a specific, documented
  set of literals.
- `open-only` — blocks licenses whose field contains "All Rights Reserved",
  "proprietary", "by-nc", or "by-nd" (non-open per the Open Definition).

These are opt-in convenience presets, not legal advice. They are a starting
point; write explicit `policies:` rules for anything you must rely on.
"""

from __future__ import annotations

PROFILES: dict[str, list[dict]] = {
    "default": [],
    "strict-optout": [
        {
            "name": "no-training-denied",
            "deny_if": {"ai_txt": {"training": "Deny"}},
            "reason": "site prohibits AI training",
        },
        {
            "name": "no-data-denied",
            "deny_if": {"ai_txt": {"data": "Deny"}},
            "reason": "site prohibits use of its content as data",
        },
        {
            "name": "no-disallow",
            "deny_if": {"ai_txt": {"disallow": True}},
            "reason": "site disallows scraping",
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
