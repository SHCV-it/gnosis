"""Compliance policy engine: granular allow/deny rules, every decision logged.

A policy is an ordered list of rules. Each rule can `allow_if` or `deny_if` a
capture based on the page's license, ai.txt directives, or URL path. **Allow
rules always take precedence**: if any allow rule matches, the capture is
allowed; otherwise the first matching deny rule blocks. Every explicit decision
is recorded in the provenance record + data card so the enforcement is
auditable, not just applied.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class PolicyDecision:
    allowed: bool
    rule: str = ""
    reason: str = ""


@dataclass
class _Rule:
    name: str
    deny: dict
    allow: dict
    reason: str


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return list(v)


def _matches(cond: dict, url: str, metadata: dict) -> bool:
    if not cond:
        return False
    if "license" in cond:
        lic = (metadata.get("license") or "").lower()
        for pattern in _as_list(cond["license"]):
            if pattern and str(pattern).lower() in lic:
                return True
    if "path" in cond:
        path = urlparse(url).path
        for pattern in _as_list(cond["path"]):
            if fnmatch.fnmatch(path, pattern):
                return True
    if "ai_txt" in cond:
        ai = metadata.get("ai_txt") or {}
        if isinstance(ai, dict):
            for key, value in cond["ai_txt"].items():
                got = str(ai.get(key) or "").lower()
                if got and got == str(value).lower():
                    return True
    return False


class PolicyEngine:
    """Evaluate allow/deny rules against a URL and its extracted metadata."""

    def __init__(self, rules: list[dict] | None = None):
        parsed = []
        for r in rules or []:
            if not isinstance(r, dict):
                raise ValueError(f"policy rule must be a dict, got {type(r).__name__}: {r!r}")
            parsed.append(
                _Rule(
                    name=str(r.get("name") or ""),
                    deny=dict(r.get("deny_if") or {}),
                    allow=dict(r.get("allow_if") or {}),
                    reason=str(r.get("reason") or "blocked by policy"),
                )
            )
        self.rules = parsed

    def evaluate(self, url: str, metadata: dict) -> PolicyDecision:
        for r in self.rules:
            if _matches(r.allow, url, metadata):
                return PolicyDecision(True, r.name or "allow", "")
        for r in self.rules:
            if _matches(r.deny, url, metadata):
                return PolicyDecision(False, r.name or "deny", r.reason)
        return PolicyDecision(True)
