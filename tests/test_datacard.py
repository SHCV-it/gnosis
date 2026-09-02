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
            "url": "https://b/y",
            "status_code": 404,
            "raw_bytes": 200,
            "markdown_chars": 10,
            "retention_ratio": 0.1,
            "stripped_elements": 0,
            "low_content": True,
            "license": "CC-BY",
        },
    ]


def test_build_data_card_aggregates():
    card = build_data_card(
        _pages(), {"source": "https://a", "mode": "crawl", "generator": "gnosis/1.4.3"}
    )
    s = card["summary"]
    assert s["pages"] == 2
    assert s["succeeded"] == 1
    assert s["failed"] == 1
    assert s["total_raw_bytes"] == 300
    assert s["total_markdown_chars"] == 60
    assert s["retention_ratio"]["min"] == 0.1
    assert s["retention_ratio"]["max"] == 0.9
    assert s["retention_ratio"]["avg"] == 0.5
    assert card["licenses_seen"] == ["CC-BY"]
    assert card["compliance"]["ai_txt_hosts"] == 1
    assert card["compliance"]["llms_txt_hosts"] == 1
    assert card["compliance"]["low_content_pages"] == 1


def test_build_data_card_empty():
    card = build_data_card([], {"source": "https://a", "mode": "single", "generator": "g"})
    assert card["summary"]["pages"] == 0
    assert card["summary"]["retention_ratio"]["avg"] is None
    assert card["licenses_seen"] == []
