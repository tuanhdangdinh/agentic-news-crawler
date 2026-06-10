"""Tests for src/agent.py tool execution — extract."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agent import AgentConfig, CrawlState, _execute_tool
from src.models import PageResult


def _page() -> PageResult:
    return PageResult(
        url="https://cafef.vn/article.chn",
        final_url="https://cafef.vn/article.chn",
        status_code=200,
        title="CafeF",
        markdown="Economy news content",
    )


@pytest.mark.asyncio
async def test_extract_returns_error_without_current_page():
    result = await _execute_tool(
        "extract",
        {"prompt": "extract title"},
        CrawlState(),
        AgentConfig(),
        "https://cafef.vn",
        0,
    )
    assert result == "error: no current page available for extraction"


@pytest.mark.asyncio
async def test_extract_stores_result_on_current_page_metadata():
    page = _page()
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    with patch("src.agent.extractor_extract", AsyncMock(return_value={"title": "CafeF"})):
        result = await _execute_tool(
            "extract",
            {"prompt": "extract title"},
            CrawlState(),
            AgentConfig(extract_schema=schema),
            "https://cafef.vn",
            0,
            current_page=page,
        )
    assert result == "{'title': 'CafeF'}"
    assert page.metadata["extracted"] == {"title": "CafeF"}


@pytest.mark.asyncio
async def test_extract_infers_schema_once_when_config_schema_missing():
    page = _page()
    config = AgentConfig()
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    with (
        patch("src.agent.infer_schema", AsyncMock(return_value=schema)) as mock_infer,
        patch("src.agent.extractor_extract", AsyncMock(return_value={"title": "CafeF"})) as mock_extract,
    ):
        result = await _execute_tool(
            "extract",
            {"prompt": "extract title"},
            CrawlState(),
            config,
            "https://cafef.vn",
            0,
            current_page=page,
        )
    assert result == "{'title': 'CafeF'}"
    mock_infer.assert_called_once_with("extract title", client=None)
    mock_extract.assert_called_once_with(page, "extract title", schema, client=None)
    assert config.extract_schema == schema


@pytest.mark.asyncio
async def test_extract_uses_registered_schema_before_inference():
    page = _page()
    config = AgentConfig()
    prompt = "extract stock tickers and key financial figures"
    with (
        patch("src.agent.infer_schema", AsyncMock()) as mock_infer,
        patch(
            "src.agent.extractor_extract",
            AsyncMock(return_value={"key_financial_figures": []}),
        ) as mock_extract,
    ):
        result = await _execute_tool(
            "extract",
            {"prompt": prompt},
            CrawlState(),
            config,
            "https://cafef.vn",
            0,
            current_page=page,
        )

    assert result == "{'key_financial_figures': []}"
    mock_infer.assert_not_called()
    assert config.extract_schema is not None
    mock_extract.assert_called_once_with(page, prompt, config.extract_schema, client=None)


@pytest.mark.asyncio
async def test_extract_stores_error_on_current_page_metadata():
    page = _page()
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    with patch("src.agent.extractor_extract", AsyncMock(return_value={"error": "bad json"})):
        result = await _execute_tool(
            "extract",
            {"prompt": "extract title"},
            CrawlState(),
            AgentConfig(extract_schema=schema),
            "https://cafef.vn",
            0,
            current_page=page,
        )
    assert result == "{'error': 'bad json'}"
    assert page.metadata["extraction_error"] == "bad json"
