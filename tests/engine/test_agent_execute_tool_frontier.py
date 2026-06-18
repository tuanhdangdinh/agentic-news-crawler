"""Tests for src/agent.py tool execution — frontier tools."""

from __future__ import annotations

import pytest

from crawl_tool.engine.agent import AgentConfig, CrawlState, _execute_tool
from crawl_tool.engine.models import PageResult


def _page() -> PageResult:
    return PageResult(
        url="https://vneconomy.vn",
        final_url="https://vneconomy.vn",
        status_code=200,
        title="VnEconomy",
        markdown="Homepage",
        links_internal=[
            "https://vneconomy.vn/article-one.htm",
            "https://vneconomy.vn/article-two.htm#comments",
        ],
        success=True,
    )


@pytest.mark.asyncio
async def test_add_to_frontier_adds_allowed_url_at_next_depth():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://cafef.vn/article.chn"},
        state,
        AgentConfig(max_depth=2),
        "https://cafef.vn",
        0,
    )
    assert result == "added at depth 1"
    assert state.frontier == [("https://cafef.vn/article.chn", 1)]


@pytest.mark.asyncio
async def test_add_to_frontier_strips_url_fragment():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://cafef.vn/article.chn#comments"},
        state,
        AgentConfig(max_depth=2),
        "https://cafef.vn",
        0,
    )
    assert result == "added at depth 1"
    assert state.frontier == [("https://cafef.vn/article.chn", 1)]


@pytest.mark.asyncio
async def test_add_to_frontier_rejects_missing_url():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {},
        state,
        AgentConfig(max_depth=2),
        "https://cafef.vn",
        0,
    )
    assert result == "error: missing required field 'url'"
    assert state.frontier == []


@pytest.mark.asyncio
async def test_add_to_frontier_rejects_depth_exceeded():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://cafef.vn/article.chn"},
        state,
        AgentConfig(max_depth=0),
        "https://cafef.vn",
        0,
    )
    assert result == "skipped (depth 1 > max 0)"
    assert state.frontier == []


@pytest.mark.asyncio
async def test_add_to_frontier_rejects_visited_url():
    state = CrawlState(visited={"https://cafef.vn/article.chn"})
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://cafef.vn/article.chn"},
        state,
        AgentConfig(max_depth=2),
        "https://cafef.vn",
        0,
    )
    assert result == "skipped (already visited)"
    assert state.frontier == []


@pytest.mark.asyncio
async def test_add_to_frontier_rejects_off_domain_url():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://vneconomy.vn/article.chn"},
        state,
        AgentConfig(max_depth=2, same_domain=True),
        "https://cafef.vn",
        0,
    )
    assert result == "skipped (blocked by guardrail)"
    assert state.frontier == []


@pytest.mark.asyncio
async def test_add_to_frontier_rejects_duplicate_frontier_url():
    state = CrawlState(frontier=[("https://cafef.vn/article.chn", 1)])
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://cafef.vn/article.chn"},
        state,
        AgentConfig(max_depth=2),
        "https://cafef.vn",
        0,
    )
    assert result == "skipped (already in frontier)"
    assert state.frontier == [("https://cafef.vn/article.chn", 1)]


@pytest.mark.asyncio
async def test_add_to_frontier_accepts_exact_current_page_link():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://vneconomy.vn/article-one.htm"},
        state,
        AgentConfig(max_depth=2),
        "https://vneconomy.vn",
        0,
        _page(),
    )
    assert result == "added at depth 1"
    assert state.frontier == [("https://vneconomy.vn/article-one.htm", 1)]


@pytest.mark.asyncio
async def test_add_to_frontier_rejects_url_not_found_in_current_page_links():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://vneconomy.vn/article-one-188260605.html"},
        state,
        AgentConfig(max_depth=2),
        "https://vneconomy.vn",
        0,
        _page(),
    )
    assert result == "skipped (not found in current page links)"
    assert state.frontier == []


@pytest.mark.asyncio
async def test_add_to_frontier_matches_current_page_links_after_stripping_fragment():
    state = CrawlState()
    result = await _execute_tool(
        "add_to_frontier",
        {"url": "https://vneconomy.vn/article-two.htm#top"},
        state,
        AgentConfig(max_depth=2),
        "https://vneconomy.vn",
        0,
        _page(),
    )
    assert result == "added at depth 1"
    assert state.frontier == [("https://vneconomy.vn/article-two.htm", 1)]
