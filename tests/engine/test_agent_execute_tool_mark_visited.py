"""Tests for src/agent.py tool execution — mark_visited."""

from __future__ import annotations

import pytest
from crawl_tool.engine.agent import AgentConfig, CrawlState, _execute_tool


@pytest.mark.asyncio
async def test_mark_visited_adds_canonical_url_to_visited():
    state = CrawlState()
    result = await _execute_tool(
        "mark_visited",
        {"url": "https://cafef.vn/article.chn#comments"},
        state,
        AgentConfig(),
        "https://cafef.vn",
        0,
    )
    assert result == "marked visited"
    assert state.visited == {"https://cafef.vn/article.chn"}
