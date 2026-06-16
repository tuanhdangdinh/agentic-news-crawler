"""Tests for src/agent.py tool execution — finish."""

from __future__ import annotations

import pytest
from crawl_tool.engine.agent import AgentConfig, CrawlState, _execute_tool


@pytest.mark.asyncio
async def test_finish_rejected_when_reachable_urls_in_frontier():
    state = CrawlState(frontier=[
        ("https://cafef.vn/article-a.chn", 1),
        ("https://cafef.vn/article-b.chn", 1),
    ])
    result = await _execute_tool(
        "finish",
        {"reason": "done"},
        state,
        AgentConfig(max_depth=1),
        "https://cafef.vn",
        1,
    )
    assert result.startswith("finish rejected:")
    assert "frontier" in result
    assert state.finished is False


@pytest.mark.asyncio
async def test_finish_accepted_when_frontier_empty():
    state = CrawlState()
    result = await _execute_tool(
        "finish",
        {"reason": "done"},
        state,
        AgentConfig(max_depth=1),
        "https://cafef.vn",
        1,
    )
    assert result == "crawl terminated"
    assert state.finished is True


@pytest.mark.asyncio
async def test_finish_rejected_before_min_article_target():
    state = CrawlState(frontier=[("https://cafef.vn/article-2.chn", 1)])
    state.article_pages = ["https://cafef.vn/article-1.chn"]
    result = await _execute_tool(
        "finish",
        {"reason": "done"},
        state,
        AgentConfig(goal="read at least 3 articles"),
        "https://cafef.vn",
        1,
        min_articles=3,
    )
    assert result.startswith("finish rejected:")
    assert state.finished is False
    assert state.finish_reason == ""


@pytest.mark.asyncio
async def test_finish_accepted_after_min_article_target():
    state = CrawlState()
    state.article_pages = [
        "https://cafef.vn/article-1.chn",
        "https://cafef.vn/article-2.chn",
        "https://cafef.vn/article-3.chn",
    ]
    result = await _execute_tool(
        "finish",
        {"reason": "done"},
        state,
        AgentConfig(goal="read at least 3 articles"),
        "https://cafef.vn",
        1,
        min_articles=3,
    )
    assert result == "crawl terminated"
    assert state.finished is True
    assert state.finish_reason == "done"
    assert state.stop_reason == "agent_finish"
