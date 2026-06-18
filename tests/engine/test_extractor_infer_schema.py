"""Tests for src/extractor.py — infer_schema."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import crawl_tool.engine.extractor as extractor_mod
from crawl_tool.engine.extractor import infer_schema


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


@pytest.mark.asyncio
async def test_infer_schema_returns_object_with_properties():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    with patch("crawl_tool.engine.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
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
    with patch("crawl_tool.engine.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(fenced))
        result = await infer_schema("extract article title")
    assert result["type"] == "object"
    assert "properties" in result


@pytest.mark.asyncio
async def test_infer_schema_preserves_strict_schema():
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "date": {"type": "string"}},
        "required": ["title", "date"],
    }
    with patch("crawl_tool.engine.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(schema)))
        result = await infer_schema("extract title and date")
    # infer_schema returns the strict schema unchanged so Claude sees required fields and
    # exact types. _make_nullable is applied only inside extract() for validation.
    assert "required" in result
    for prop in result["properties"].values():
        assert prop["type"] == "string"


@pytest.mark.asyncio
async def test_infer_schema_returns_fallback_on_invalid_json(caplog):
    with patch("crawl_tool.engine.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response("not valid json"))
        with caplog.at_level(logging.WARNING, logger="crawl_tool.engine.extractor"):
            result = await infer_schema("extract title")
    assert result == {"type": "object", "properties": {}}
    assert any("infer_schema JSON parse error" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_infer_schema_returns_fallback_on_invalid_schema(caplog):
    # type must be a string or array, not an integer — structurally invalid schema
    bad_schema = {"type": 42, "properties": {}}
    with patch("crawl_tool.engine.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(bad_schema)))
        with caplog.at_level(logging.WARNING, logger="crawl_tool.engine.extractor"):
            result = await infer_schema("extract price")
    assert result == {"type": "object", "properties": {}}
    assert any("infer_schema invalid schema" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_infer_schema_caches_result():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    prompt = "cache test prompt — unique string"
    extractor_mod._schema_cache.pop(prompt, None)
    with patch("crawl_tool.engine.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(json.dumps(schema)))
        await infer_schema(prompt)
        await infer_schema(prompt)
        assert mock_client.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_infer_schema_cache_hit_skips_api():
    schema = {"type": "object", "properties": {"price": {"type": ["number", "null"]}}}
    prompt = "cache hit test — unique string"
    extractor_mod._schema_cache[prompt] = schema
    with patch("crawl_tool.engine.extractor.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        result = await infer_schema(prompt)
        mock_client.messages.create.assert_not_called()
    assert result is schema
    extractor_mod._schema_cache.pop(prompt)
