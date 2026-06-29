"""Tests for ui_shared helpers."""

from __future__ import annotations


def test_s_strips_and_returns_empty_for_none():
    from crawl_tool.gradio.ui_shared import _s

    assert _s(None) == ""
    assert _s("  hello  ") == "hello"


def test_parse_patterns_removes_blank_lines():
    from crawl_tool.gradio.ui_shared import _parse_patterns

    assert _parse_patterns("  *article*\n\n *video*  ") == ["*article*", "*video*"]
    assert _parse_patterns(None) == []


def test_build_request_assembles_dict():
    from crawl_tool.gradio.ui_shared import _build_request

    request = _build_request(
        "https://cafef.vn",
        " collect news ",
        " extract title ",
        '{"type": "object", "properties": {}}',
        2,
        5,
        1000,
        False,
        "*article*\n*news*",
        "*video*",
        " last 7 days ",
        False,
        " article ",
        8000,
    )
    assert request["seed_url"] == "https://cafef.vn"
    assert request["goal"] == "collect news"
    assert request["max_depth"] == 2
    assert request["extract_schema"] == {"type": "object", "properties": {}}
    assert request["include_patterns"] == ["*article*", "*news*"]
