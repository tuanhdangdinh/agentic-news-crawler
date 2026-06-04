"""Tests for src/extractor.py — infer_schema."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.extractor import infer_schema


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


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
    assert any("infer_schema JSON parse error" in r.message for r in caplog.records)
