"""Tests for src/extractor.py — extract, infer_schema."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.extractor import extract, infer_schema
from src.models import PageResult


def _page(markdown: str = "Article about GDP growth in Vietnam") -> PageResult:
    return PageResult(
        url="https://cafef.vn/article.chn",
        final_url="https://cafef.vn/article.chn",
        status_code=200,
        title="Economy article",
        markdown=markdown,
    )


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


# ---------------------------------------------------------------------------
# infer_schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_infer_schema_returns_object_with_properties():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(schema)))
        result = await infer_schema("extract article title")
    assert result["type"] == "object"
    assert "properties" in result


@pytest.mark.asyncio
async def test_infer_schema_strips_markdown_fences():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    fenced = f"```json\n{json.dumps(schema)}\n```"
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(fenced))
        result = await infer_schema("extract article title")
    assert result["type"] == "object"
    assert "properties" in result


@pytest.mark.asyncio
async def test_infer_schema_strips_required_and_allows_null():
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "date": {"type": "string"}},
        "required": ["title", "date"],
    }
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(schema)))
        result = await infer_schema("extract title and date")
    assert "required" not in result
    for prop in result["properties"].values():
        assert "null" in prop["type"]


@pytest.mark.asyncio
async def test_infer_schema_returns_fallback_on_invalid_json(caplog):
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response("not valid json"))
        with caplog.at_level(logging.WARNING, logger="src.extractor"):
            result = await infer_schema("extract title")
    assert result == {"type": "object", "properties": {}}
    assert any("failed to parse" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_returns_dict_with_keys():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    payload = {"title": "GDP tăng 6.5%"}
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(payload)))
        result = await extract(_page(), "extract title", schema=schema)
    assert "title" in result
    assert result["title"] == "GDP tăng 6.5%"


@pytest.mark.asyncio
async def test_extract_passes_schema_validation():
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    payload = {"title": "Economy news"}
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(payload)))
        result = await extract(_page(), "extract title", schema=schema)
    assert "error" not in result


@pytest.mark.asyncio
async def test_extract_returns_error_dict_on_schema_violation(caplog):
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["missing_field"],
    }
    payload = {"title": "Economy news"}
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(payload)))
        with caplog.at_level(logging.WARNING, logger="src.extractor"):
            result = await extract(_page(), "extract title", schema=schema)
    assert "error" in result
    assert "raw" in result
    assert any("schema validation failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_extract_returns_error_on_empty_markdown():
    result = await extract(_page(markdown=""), "extract title")
    assert result["error"] == "page has no markdown content"
    assert result["raw"] == ""


@pytest.mark.asyncio
async def test_extract_strips_markdown_fences():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    payload = {"title": "GDP tăng 6.5%"}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(fenced))
        result = await extract(_page(), "extract title", schema=schema)
    assert result.get("title") == "GDP tăng 6.5%"


@pytest.mark.asyncio
async def test_extract_returns_error_on_invalid_json_response(caplog):
    schema = {"type": "object", "properties": {}}
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response("not json"))
        with caplog.at_level(logging.WARNING, logger="src.extractor"):
            result = await extract(_page(), "extract title", schema=schema)
    assert "error" in result
    assert "JSON parse error" in result["error"]
    assert any("JSON parse error" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_extract_does_not_raise_on_api_error(caplog):
    schema = {"type": "object", "properties": {}}
    with patch("src.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))
        with caplog.at_level(logging.WARNING, logger="src.extractor"):
            result = await extract(_page(), "extract title", schema=schema)
    assert "error" in result
    assert any("Claude API error" in r.message for r in caplog.records)
