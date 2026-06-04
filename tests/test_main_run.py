"""Tests for main.py — run."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from main import build_parser, run
from src.agent import CrawlState
from src.models import PageResult


def _page(success: bool = True) -> PageResult:
    return PageResult(
        url="https://cafef.vn",
        final_url="https://cafef.vn",
        status_code=200 if success else 500,
        title="CafeF",
        markdown="Economy news content",
        links_internal=["https://cafef.vn/article.chn"],
        success=success,
        error=None if success else "fetch failed",
    )


@pytest.mark.asyncio
async def test_run_direct_fetch_writes_single_page_result():
    args = build_parser().parse_args(["https://cafef.vn", "--output", "out.json"])
    with (
        patch("main.configure_logging"),
        patch("main.fetch_page", AsyncMock(return_value=_page())) as mock_fetch,
        patch("main.write_results") as mock_write,
    ):
        await run(args)
    mock_fetch.assert_called_once_with("https://cafef.vn")
    mock_write.assert_called_once()
    pages, path = mock_write.call_args.args[:2]
    assert pages == [_page()]
    assert path == "out.json"
    assert mock_write.call_args.kwargs["fmt"] == "json"
    assert mock_write.call_args.kwargs["run_meta"]["max_pages"] == 1


@pytest.mark.asyncio
async def test_run_agent_wires_week_3_config_flags():
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
    state = CrawlState(pages=[_page()], visited={"https://cafef.vn"})
    with (
        patch("main.configure_logging"),
        patch("main.run_agent", AsyncMock(return_value=state)) as mock_run_agent,
        patch("main.write_results"),
    ):
        await run(args)
    config = mock_run_agent.call_args.args[1]
    assert config.goal == "collect economy news"
    assert config.max_depth == 2
    assert config.max_pages == 5
    assert config.token_budget == 1000
    assert config.same_domain is False
    assert config.include_patterns == ["*cafef.vn*"]
    assert config.exclude_patterns == ["*video*"]


@pytest.mark.asyncio
async def test_run_agent_wires_week_4_extraction_config(tmp_path):
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--goal",
        "collect economy news",
        "--extract-prompt",
        "extract title",
        "--extract-schema",
        str(schema_path),
    ])
    state = CrawlState(pages=[_page()], visited={"https://cafef.vn"})
    with (
        patch("main.configure_logging"),
        patch("main.run_agent", AsyncMock(return_value=state)) as mock_run_agent,
        patch("main.write_results"),
    ):
        await run(args)
    config = mock_run_agent.call_args.args[1]
    assert config.extract_prompt == "extract title"
    assert config.extract_schema == schema


@pytest.mark.asyncio
async def test_run_missing_extract_schema_file_skips_agent():
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--goal",
        "collect economy news",
        "--extract-schema",
        "missing-schema.json",
    ])
    with (
        patch("main.configure_logging"),
        patch("main.run_agent", AsyncMock()) as mock_run_agent,
        patch("main.write_results") as mock_write,
    ):
        await run(args)
    mock_run_agent.assert_not_called()
    mock_write.assert_not_called()
