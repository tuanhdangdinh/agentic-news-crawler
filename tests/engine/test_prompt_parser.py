"""Tests for src/prompt_parser.py -- parse_crawl_prompt."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawl_tool.engine.prompt_parser import PromptParseError, parse_crawl_prompt


def _mock_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.stop_reason = stop_reason
    return msg


@pytest.mark.asyncio
async def test_parse_crawl_prompt_returns_all_specified_fields():
    data = {
        "seed_url": "https://vnexpress.net",
        "goal": "collect tech news",
        "max_pages": 50,
    }
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        result = await parse_crawl_prompt("crawl vnexpress.net for tech news, max 50 pages")
    assert result == data


@pytest.mark.asyncio
async def test_parse_crawl_prompt_strips_markdown_fences():
    data = {"seed_url": "https://vnexpress.net"}
    fenced = f"```json\n{json.dumps(data)}\n```"
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(fenced))
        result = await parse_crawl_prompt("crawl vnexpress.net")
    assert result == data


@pytest.mark.asyncio
async def test_parse_crawl_prompt_returns_only_specified_keys():
    data = {"seed_url": "https://vnexpress.net", "goal": "tech news"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        result = await parse_crawl_prompt("crawl vnexpress.net for tech news")
    assert set(result.keys()) == {"seed_url", "goal"}


@pytest.mark.asyncio
async def test_parse_crawl_prompt_rejects_schemeless_url():
    data = {"seed_url": "vnexpress.net"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_missing_seed_url_raises():
    data = {"goal": "tech news"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("collect tech news")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_invalid_json_raises():
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response("not valid json"))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_schema_violation_raises():
    data = {"seed_url": "https://vnexpress.net", "max_pages": "fifty"}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net, fifty pages")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_rejects_max_depth_above_ceiling():
    data = {"seed_url": "https://vnexpress.net", "max_depth": 10}
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(data)))
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net 10 levels deep")


@pytest.mark.asyncio
async def test_parse_crawl_prompt_truncated_response_raises():
    with patch("crawl_tool.engine.prompt_parser.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response("{}", stop_reason="max_tokens")
        )
        with pytest.raises(PromptParseError):
            await parse_crawl_prompt("crawl vnexpress.net")
