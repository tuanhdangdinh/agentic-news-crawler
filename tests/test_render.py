"""Tests for src/prompts.py — render."""

from __future__ import annotations

import logging

import pytest
from jinja2 import TemplateNotFound, UndefinedError

from src.prompts import render

_SYSTEM_CTX = {
    "goal": "collect economy news",
    "today": "2026-06-03",
    "max_depth": 1,
    "max_pages": 10,
    "same_domain": True,
    "extract_prompt": "",
}

_USER_CTX = {
    "url": "https://cafef.vn",
    "title": "CafeF",
    "depth": 0,
    "max_depth": 1,
    "markdown": "Sample content",
    "links_internal": ["https://cafef.vn/article.chn"],
    "pages_count": 0,
    "article_pages_count": 0,
    "min_articles": 0,
    "frontier_count": 1,
    "frontier_reachable": 1,
    "visited_count": 0,
    "tokens_used": 0,
    "token_budget": 500_000,
}


@pytest.mark.parametrize(
    ("template", "ctx", "expected_substring"),
    [
        ("system.j2", _SYSTEM_CTX, "collect economy news"),
        ("user_turn.j2", _USER_CTX, "https://cafef.vn"),
    ],
)
def test_render_returns_nonempty_string_containing_context(template, ctx, expected_substring):
    result = render(template, **ctx)
    assert isinstance(result, str)
    assert len(result) > 0
    assert expected_substring in result


def test_render_missing_variable_raises_undefined_error():
    with pytest.raises(UndefinedError):
        render("system.j2", goal="test")  # missing max_depth, max_pages, same_domain


def test_render_nonexistent_template_raises_not_found():
    with pytest.raises(TemplateNotFound):
        render("nonexistent_template.j2", foo="bar")


def test_render_system_includes_extract_prompt_when_set():
    ctx = {**_SYSTEM_CTX, "extract_prompt": "extract title and date"}
    result = render("system.j2", **ctx)
    assert "extract title and date" in result


def test_render_system_omits_extraction_block_when_prompt_empty():
    result = render("system.j2", **_SYSTEM_CTX)
    assert "extract_prompt" not in result


def test_render_logs_nothing_on_success(caplog):
    with caplog.at_level(logging.WARNING, logger="src.prompts"):
        render("system.j2", **_SYSTEM_CTX)
    assert caplog.records == []
