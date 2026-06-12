"""Tests for the Gradio crawl interface backend."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from crawl_engine.agent import CrawlState
from crawl_engine.models import PageResult
from crawl_gradio.ui import _build_config, _parse_patterns, run_crawl


def _page() -> PageResult:
    return PageResult(
        url="https://cafef.vn",
        final_url="https://cafef.vn",
        status_code=200,
        title="CafeF",
        markdown="Economy news content",
    )


def test_parse_patterns_removes_blank_lines_and_whitespace():
    assert _parse_patterns("  *article*\n\n *video*  ") == ["*article*", "*video*"]


def test_build_config_parses_schema_and_controls():
    config = _build_config(
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

    assert config.goal == "collect news"
    assert config.extract_prompt == "extract title"
    assert config.extract_schema == {"type": "object", "properties": {}}
    assert config.max_depth == 2
    assert config.max_pages == 5
    assert config.token_budget == 1000
    assert config.same_domain is False
    assert config.include_patterns == ["*article*", "*news*"]
    assert config.exclude_patterns == ["*video*"]
    assert config.date_filter == "last 7 days"
    assert config.include_undated is False
    assert config.css_selector == "article"
    assert config.max_chars == 8000


@pytest.mark.asyncio
async def test_run_crawl_uses_direct_fetch_without_goal_or_extraction(tmp_path):
    output_path = tmp_path / "result.json"
    with (
        patch("crawl_gradio.ui.fetch_page", AsyncMock(return_value=_page())) as mock_fetch,
        patch("crawl_gradio.ui._output_path", return_value=str(output_path)),
    ):
        status, _table_html, payload, _payload2, _extraction_req, download = await run_crawl(
            "https://cafef.vn",
            "",
            "",
            "",
            1,
            10,
            500_000,
            True,
            "",
            "",
            "",
            True,
            "",
            0,
            "JSON",
        )

    mock_fetch.assert_awaited_once_with("https://cafef.vn", css_selector=None)
    assert status == "Collected 1 page(s), 1 successful, 0 failed."
    assert payload["meta"]["max_pages"] == 1
    assert payload["pages"][0]["title"] == "CafeF"
    assert download == str(output_path)
    assert output_path.exists()


@pytest.mark.asyncio
async def test_run_crawl_uses_agent_when_goal_is_present(tmp_path):
    output_path = tmp_path / "result.jsonl"
    state = CrawlState(
        pages=[_page()],
        visited={"https://cafef.vn"},
        article_pages=["https://cafef.vn/article.chn"],
        stop_reason="max_pages",
    )
    with (
        patch("crawl_gradio.ui.run_agent", AsyncMock(return_value=state)) as mock_run_agent,
        patch("crawl_gradio.ui._output_path", return_value=str(output_path)),
    ):
        _, _table_html, payload, _payload2, _extraction_req, download = await run_crawl(
            "https://cafef.vn",
            "collect economy news",
            "extract title",
            "",
            2,
            5,
            1000,
            False,
            "*article*",
            "*video*",
            "last 7 days",
            False,
            "article",
            8000,
            "JSONL",
        )

    config = mock_run_agent.call_args.args[1]
    assert config.goal == "collect economy news"
    assert config.extract_prompt == "extract title"
    assert config.max_depth == 2
    assert config.max_pages == 5
    assert payload["meta"]["article_pages_collected"] == 1
    assert payload["meta"]["stop_reason"] == "max_pages"
    assert download == str(output_path)
    assert output_path.exists()
