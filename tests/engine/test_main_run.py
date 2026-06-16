"""Tests for main.py — run."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from crawl_tool.engine.cli import build_parser, run


@pytest.mark.asyncio
async def test_run_direct_fetch_writes_single_page_result(tmp_path):
    out = tmp_path / "out.jsonl"
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--css-selector",
        "main",
        "--output",
        str(out),
        "--format",
        "jsonl",
    ])
    payload = {
        "meta": {"total_pages": 1},
        "pages": [{"url": "https://cafef.vn", "title": "CafeF"}],
    }
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)) as mock_execute,
    ):
        await run(args)
    request, state = mock_execute.call_args.args
    assert request.seed_url == "https://cafef.vn"
    assert request.goal == ""
    assert request.extract_prompt == ""
    assert request.css_selector == "main"
    assert state.pages == []
    assert out.read_text(encoding="utf-8") == json.dumps(payload["pages"][0])


@pytest.mark.asyncio
async def test_run_agent_wires_week_3_config_flags(tmp_path):
    out = tmp_path / "out.json"
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
        "--output",
        str(out),
    ])
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)) as mock_execute,
    ):
        await run(args)
    request = mock_execute.call_args.args[0]
    assert request.seed_url == "https://cafef.vn"
    assert request.goal == "collect economy news"
    assert request.max_depth == 2
    assert request.max_pages == 5
    assert request.token_budget == 1000
    assert request.same_domain is False
    assert request.include_patterns == ["*cafef.vn*"]
    assert request.exclude_patterns == ["*video*"]
    assert json.loads(out.read_text(encoding="utf-8")) == payload


@pytest.mark.asyncio
async def test_run_agent_wires_week_4_extraction_config(tmp_path):
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    out = tmp_path / "out.json"
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--goal",
        "collect economy news",
        "--extract-prompt",
        "extract title",
        "--extract-schema",
        str(schema_path),
        "--date-filter",
        "last 7 days",
        "--include-undated",
        "--max-chars",
        "2000",
        "--output",
        str(out),
    ])
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)) as mock_execute,
    ):
        await run(args)
    request = mock_execute.call_args.args[0]
    assert request.extract_prompt == "extract title"
    assert request.extract_schema == schema
    assert request.date_filter == "last 7 days"
    assert request.include_undated is True
    assert request.max_chars == 2000
    assert json.loads(out.read_text(encoding="utf-8")) == payload


@pytest.mark.asyncio
async def test_run_max_depth_above_ceiling_skips_agent():
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--goal",
        "collect economy news",
        "--max-depth",
        "6",
    ])
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock()) as mock_execute,
    ):
        await run(args)
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_negative_max_depth_skips_agent():
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--goal",
        "collect economy news",
        "--max-depth",
        "-1",
    ])
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock()) as mock_execute,
    ):
        await run(args)
    mock_execute.assert_not_awaited()


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
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock()) as mock_execute,
    ):
        await run(args)
    mock_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_dispatches_schema_file_operations_to_thread(tmp_path):
    schema = {"type": "object"}
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    out = tmp_path / "out.json"
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--goal",
        "collect economy news",
        "--extract-schema",
        str(schema_path),
        "--output",
        str(out),
    ])
    payload = {"meta": {"total_pages": 0}, "pages": []}
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)),
        patch("crawl_tool.engine.cli.asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread,
    ):
        await run(args)
    dispatched = [call.args[0].__name__ for call in mock_to_thread.await_args_list]
    assert dispatched[:2] == ["exists", "read_text"]


@pytest.mark.asyncio
async def test_run_dispatches_output_write_to_thread(tmp_path):
    out = tmp_path / "out.json"
    args = build_parser().parse_args([
        "https://cafef.vn",
        "--goal",
        "collect economy news",
        "--output",
        str(out),
    ])
    payload = {"meta": {"total_pages": 0}, "pages": []}
    expected = json.dumps(payload, ensure_ascii=False, indent=2)
    with (
        patch("crawl_tool.engine.cli.configure_logging"),
        patch("crawl_tool.engine.cli.execute", AsyncMock(return_value=payload)),
        patch("crawl_tool.engine.cli.asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread,
    ):
        await run(args)
    write_call = mock_to_thread.await_args_list[-1]
    assert write_call.args[0].__name__ == "write_text"
    assert write_call.args[1] == expected
    assert write_call.kwargs == {"encoding": "utf-8"}
