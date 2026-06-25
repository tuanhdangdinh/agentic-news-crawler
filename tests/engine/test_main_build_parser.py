"""Tests for main.py — build_parser."""

from __future__ import annotations

from crawl_tool.engine.cli import build_parser


def test_build_parser_accepts_output_and_format_flags():
    args = build_parser().parse_args(
        [
            "https://cafef.vn",
            "--output",
            "out.jsonl",
            "--format",
            "jsonl",
            "--verbose",
        ]
    )
    assert args.url == "https://cafef.vn"
    assert args.output == "out.jsonl"
    assert args.format == "jsonl"
    assert args.verbose is True


def test_build_parser_accepts_agent_crawl_flags():
    args = build_parser().parse_args(
        [
            "https://cafef.vn",
            "--goal",
            "collect economy news",
            "--max-depth",
            "2",
            "--max-pages",
            "5",
            "--token-budget",
            "1000",
            "--no-same-domain",
            "--include-pattern",
            "*cafef.vn*",
            "--exclude-pattern",
            "*video*",
        ]
    )
    assert args.goal == "collect economy news"
    assert args.max_depth == 2
    assert args.max_pages == 5
    assert args.token_budget == 1000
    assert args.same_domain is False
    assert args.include_pattern == ["*cafef.vn*"]
    assert args.exclude_pattern == ["*video*"]


def test_build_parser_accepts_extraction_flags():
    args = build_parser().parse_args(
        [
            "https://cafef.vn",
            "--extract-prompt",
            "extract title",
            "--extract-schema",
            "schema.json",
        ]
    )
    assert args.extract_prompt == "extract title"
    assert args.extract_schema == "schema.json"


def test_build_parser_accepts_date_flags():
    args = build_parser().parse_args(
        [
            "https://cafef.vn",
            "--date-filter",
            "last 7 days",
            "--include-undated",
        ]
    )
    assert args.date_filter == "last 7 days"
    assert args.include_undated is True


def test_build_parser_accepts_css_selector_and_max_chars():
    args = build_parser().parse_args(
        [
            "https://cafef.vn",
            "--css-selector",
            "article.main-content",
            "--max-chars",
            "8000",
        ]
    )
    assert args.css_selector == "article.main-content"
    assert args.max_chars == 8000


def test_build_parser_css_selector_defaults_empty_max_chars_defaults_zero():
    args = build_parser().parse_args(["https://cafef.vn"])
    assert args.css_selector == ""
    assert args.max_chars == 0


def test_build_parser_url_is_optional_when_prompt_used():
    args = build_parser().parse_args(["--prompt", "crawl vnexpress.net"])
    assert args.url is None
    assert args.prompt == "crawl vnexpress.net"


def test_build_parser_override_flags_default_to_none():
    args = build_parser().parse_args(["https://cafef.vn"])
    assert args.goal is None
    assert args.extract_prompt is None
    assert args.max_depth is None
    assert args.max_pages is None
    assert args.date_filter is None
    assert args.include_undated is None
    assert args.same_domain is None
    assert args.include_pattern is None
    assert args.exclude_pattern is None


def test_build_query_parser_accepts_all_flags():
    from crawl_tool.engine.cli import build_query_parser
    args = build_query_parser().parse_args([
        "--seed-url", "vietnamnet.vn",
        "--goal", "finance",
        "--date-from", "2026-06-01",
        "--date-to", "2026-06-30",
        "--limit", "5",
        "--engine-url", "http://myhost:8000",
    ])
    assert args.seed_url == "vietnamnet.vn"
    assert args.goal == "finance"
    assert args.date_from == "2026-06-01"
    assert args.date_to == "2026-06-30"
    assert args.limit == 5
    assert args.engine_url == "http://myhost:8000"
