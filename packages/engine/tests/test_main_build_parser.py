"""Tests for main.py — build_parser."""

from __future__ import annotations

from crawl_engine.cli import build_parser


def test_build_parser_accepts_output_and_format_flags():
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--output",
        "out.jsonl",
        "--format",
        "jsonl",
        "--verbose",
    ])
    assert args.url == "https://cafef.vn"
    assert args.output == "out.jsonl"
    assert args.format == "jsonl"
    assert args.verbose is True


def test_build_parser_accepts_agent_crawl_flags():
    args = build_parser().parse_args([
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
    ])
    assert args.goal == "collect economy news"
    assert args.max_depth == 2
    assert args.max_pages == 5
    assert args.token_budget == 1000
    assert args.same_domain is False
    assert args.include_pattern == ["*cafef.vn*"]
    assert args.exclude_pattern == ["*video*"]


def test_build_parser_accepts_extraction_flags():
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--extract-prompt",
        "extract title",
        "--extract-schema",
        "schema.json",
    ])
    assert args.extract_prompt == "extract title"
    assert args.extract_schema == "schema.json"


def test_build_parser_accepts_date_flags():
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--date-filter",
        "last 7 days",
        "--include-undated",
    ])
    assert args.date_filter == "last 7 days"
    assert args.include_undated is True


def test_build_parser_accepts_css_selector_and_max_chars():
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--css-selector",
        "article.main-content",
        "--max-chars",
        "8000",
    ])
    assert args.css_selector == "article.main-content"
    assert args.max_chars == 8000


def test_build_parser_css_selector_defaults_empty_max_chars_defaults_zero():
    args = build_parser().parse_args(["https://cafef.vn"])
    assert args.css_selector == ""
    assert args.max_chars == 0
