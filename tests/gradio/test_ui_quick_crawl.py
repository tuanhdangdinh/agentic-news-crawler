"""Tests for quick crawl page helpers."""
from __future__ import annotations


def test_populate_fields_fills_parsed_values():
    from crawl_tool.gradio.ui_quick_crawl import _populate_fields
    parsed = {
        "seed_url": "https://cafef.vn",
        "goal": "finance news",
        "date_filter": "last 7 days",
        "extract_prompt": "extract title",
        "max_depth": 2,
        "max_pages": 15,
    }
    updates = _populate_fields(parsed)
    # returns a tuple of 6 gr.update dicts in order:
    # seed_url, goal, date_filter, extract_prompt, max_depth, max_pages
    assert len(updates) == 6
    assert updates[0]["value"] == "https://cafef.vn"
    assert updates[1]["value"] == "finance news"
    assert updates[2]["value"] == "last 7 days"
    assert updates[3]["value"] == "extract title"
    assert updates[4]["value"] == 2
    assert updates[5]["value"] == 15


def test_populate_fields_uses_defaults_for_missing_keys():
    from crawl_tool.gradio.ui_quick_crawl import _populate_fields
    parsed = {"seed_url": "https://cafef.vn"}
    updates = _populate_fields(parsed)
    assert updates[1]["value"] == ""       # goal default
    assert updates[4]["value"] == 1        # max_depth default
    assert updates[5]["value"] == 10       # max_pages default


def test_inferred_chip_html_marks_found_fields():
    from crawl_tool.gradio.ui_quick_crawl import _inferred_chip_html
    html = _inferred_chip_html({"seed_url": "https://cafef.vn", "goal": "news"})
    assert "seed_url" in html
    assert "goal" in html
    assert "✓" in html


def test_inferred_chip_html_marks_default_fields():
    from crawl_tool.gradio.ui_quick_crawl import _inferred_chip_html
    html = _inferred_chip_html({"seed_url": "https://cafef.vn"})
    assert "date_filter" in html
    assert "default" in html.lower() or "—" in html
