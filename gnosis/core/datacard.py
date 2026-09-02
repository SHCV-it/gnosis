"""Data Cards for scrape/crawl jobs (Hugging Face dataset-card style).

A Data Card summarises one scrape or crawl run — sources, sizes, licenses
encountered, and key compliance decisions — so a downstream human or auditor
can see what a batch of captured documents contains without opening each file.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = "1.0"


def build_data_card(pages: list[dict], job: dict) -> dict:
    """Build a data card dict from per-page records + job metadata."""
    n = len(pages)
    total_raw = sum(p.get("raw_bytes", 0) for p in pages)
    total_md = sum(p.get("markdown_chars", 0) for p in pages)
    ratios = [
        p["retention_ratio"]
        for p in pages
        if p.get("retention_ratio") is not None
    ]
    licenses = sorted({p["license"] for p in pages if p.get("license")})
    ai_hosts = len({p["url"] for p in pages if p.get("ai_txt")})
    llms_hosts = len({p["url"] for p in pages if p.get("llms_txt")})
    return {
        "schema_version": SCHEMA_VERSION,
        "job": job,
        "summary": {
            "pages": n,
            "succeeded": sum(1 for p in pages if p.get("status_code", 0) < 400),
            "failed": sum(
                1 for p in pages if p.get("status_code", 0) >= 400 or p.get("error")
            ),
            "total_raw_bytes": total_raw,
            "total_markdown_chars": total_md,
            "retention_ratio": {
                "min": round(min(ratios), 4) if ratios else None,
                "max": round(max(ratios), 4) if ratios else None,
                "avg": round(sum(ratios) / len(ratios), 4) if ratios else None,
            },
        },
        "licenses_seen": licenses,
        "compliance": {
            "ai_txt_hosts": ai_hosts,
            "llms_txt_hosts": llms_hosts,
            "low_content_pages": sum(1 for p in pages if p.get("low_content")),
        },
        "pages": pages,
    }


def write_data_card(output_dir: Path, pages: list[dict], job: dict) -> Path:
    """Write a data-card.json for a run; return the written path."""
    card = build_data_card(pages, job)
    path = Path(output_dir) / "data-card.json"
    path.write_text(
        json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path
