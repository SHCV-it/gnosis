"""Tests for data card generation."""

from gnosis.core.datacard import build_data_card


def _pages():
    return [
        {
            "url": "https://a/x",
            "status_code": 200,
            "raw_bytes": 100,
            "markdown_chars": 50,
            "retention_ratio": 0.9,
            "stripped_elements": 3,
            "low_content": False,
            "license": "CC-BY",
            "ai_txt": {"training": "Allow"},
            "llms_txt": True,
        },
        {
            "url": "https://a/y",
            "status_code": 200,
            "raw_bytes": 150,
            "markdown_chars": 60,
            "retention_ratio": 0.5,
            "stripped_elements": 1,
            "low_content": False,
            "license": "CC-BY",
            "ai_txt": {"training": "Allow"},
        },
        {
            "url": "https://b/z",
            "status_code": None,
            "raw_bytes": 0,
            "markdown_chars": 0,
            "error": "boom",
        },
    ]


def test_build_data_card_aggregates():
    card = build_data_card(
        _pages(), {"source": "https://a", "mode": "crawl", "generator": "gnosis/1.4.3"}
    )
    s = card["summary"]
    assert s["pages"] == 3
    assert s["succeeded"] == 2
    assert s["failed"] == 1
    assert s["total_raw_bytes"] == 250
    assert s["total_markdown_chars"] == 110
    assert s["retention_ratio"]["min"] == 0.5
    assert s["retention_ratio"]["max"] == 0.9
    assert round(s["retention_ratio"]["avg"], 4) == 0.7
    assert card["licenses_seen"] == ["CC-BY"]


def test_compliance_hosts_dedupe_by_host():
    """Regression (reviewer P1): ai_txt_hosts must count HOSTS, not pages.

    Two pages on the same host both carrying ai_txt must count as 1 host.
    """
    card = build_data_card(_pages(), {"source": "https://a", "mode": "crawl", "generator": "g"})
    assert card["compliance"]["ai_txt_hosts"] == 1
    assert card["compliance"]["llms_txt_hosts"] == 1
    assert card["compliance"]["low_content_pages"] == 0


def test_failed_records_are_not_counted_success():
    """Regression (reviewer P1): a failed record (error, no status) must not
    inflate succeeded, and must appear in failed."""
    card = build_data_card(_pages(), {"source": "https://a", "mode": "crawl", "generator": "g"})
    assert card["summary"]["succeeded"] == 2
    assert card["summary"]["failed"] == 1


def test_build_data_card_empty():
    card = build_data_card([], {"source": "https://a", "mode": "single", "generator": "g"})
    assert card["summary"]["pages"] == 0
    assert card["summary"]["retention_ratio"]["avg"] is None
    assert card["licenses_seen"] == []


def test_none_status_tolerated():
    """Regression (#61): a page with status_code=None (and no error) must not
    crash build_data_card."""
    card = build_data_card(
        [{"url": "https://x", "status_code": None}],
        {"source": "x", "mode": "crawl", "generator": "g"},
    )
    assert card["summary"]["pages"] == 1
