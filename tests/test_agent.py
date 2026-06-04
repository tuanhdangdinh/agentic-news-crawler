"""Tests for src/agent.py — run_agent."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent import (
    AgentConfig,
    CrawlState,
    _execute_tool,
    _is_article_page,
    _parse_min_articles,
    run_agent,
)
from src.models import PageResult

_INFERRED_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}


def _page(url: str = "https://cafef.vn", success: bool = True) -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=200 if success else 500,
        title="CafeF",
        markdown="Economy news content",
        links_internal=["https://cafef.vn/article-1.chn", "https://cafef.vn/article-2.chn"],
        success=success,
        error=None if success else "fetch failed",
    )


def _article_page(url: str = "https://cafef.vn/gia-vang-188260603074758376.chn") -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=200,
        title="Article",
        markdown="Article content",
        links_internal=[],
        metadata={"article:published_time": "2026-06-03T09:16:00+07:00"},
        success=True,
        error=None,
    )


def _finish_response() -> MagicMock:
    """Claude response that calls finish immediately."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "finish"
    block.id = "tool_1"
    block.input = {"reason": "goal satisfied"}

    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    response.usage = MagicMock(input_tokens=100, output_tokens=50)
    return response


def _end_turn_response() -> MagicMock:
    """Claude response with no tool calls."""
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = []
    response.usage = MagicMock(input_tokens=100, output_tokens=50)
    return response


def _add_url_response(url: str) -> MagicMock:
    """Claude response that adds one URL then ends."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "add_to_frontier"
    block.id = "tool_1"
    block.input = {"url": url, "reason": "relevant article"}

    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    response.usage = MagicMock(input_tokens=100, output_tokens=50)
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("fetch and read at least 3 economy news articles", 3),
        ("minimum 5 articles about banks", 5),
        ("read three economy news articles", 3),
        ("collect news about gold", 0),
    ],
)
def test_parse_min_articles(goal: str, expected: int):
    assert _parse_min_articles(goal) == expected


def test_is_article_page_detects_cafef_article_url():
    assert _is_article_page(_page("https://cafef.vn/gia-vang-188260603074758376.chn"))


def test_is_article_page_detects_article_metadata():
    assert _is_article_page(_article_page("https://example.com/news/gold"))


def test_is_article_page_rejects_homepage_and_category():
    assert not _is_article_page(_page("https://cafef.vn"))
    assert not _is_article_page(_page("https://cafef.vn/tai-chinh-ngan-hang.chn"))


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# run_agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_infers_schema_once_before_loop():
    config = AgentConfig(
        goal="collect news", max_pages=1,
        extract_prompt="extract title", extract_schema=None,
    )
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
        patch("src.agent.infer_schema", AsyncMock(return_value=_INFERRED_SCHEMA)) as mock_infer,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    mock_infer.assert_called_once()
    assert config.extract_schema == _INFERRED_SCHEMA


@pytest.mark.asyncio
async def test_run_agent_skips_infer_schema_when_schema_provided():
    config = AgentConfig(
        goal="collect news", max_pages=1,
        extract_prompt="extract title", extract_schema=_INFERRED_SCHEMA,
    )
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
        patch("src.agent.infer_schema", AsyncMock(return_value=_INFERRED_SCHEMA)) as mock_infer,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    mock_infer.assert_not_called()


@pytest.mark.asyncio
async def test_run_agent_stores_depth_in_page_metadata():
    config = AgentConfig(goal="collect news", max_pages=1)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        state = await run_agent("https://cafef.vn", config)
    assert state.pages[0].metadata["depth"] == 0


@pytest.mark.asyncio
async def test_run_agent_returns_crawl_state_with_pages():
    config = AgentConfig(goal="collect news", max_pages=1)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        state = await run_agent("https://cafef.vn", config)
    assert isinstance(state, CrawlState)
    assert len(state.pages) > 0
    assert len(state.visited) > 0


@pytest.mark.asyncio
async def test_run_agent_respects_max_pages():
    config = AgentConfig(max_pages=1)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        state = await run_agent("https://cafef.vn", config)
    assert len(state.pages) <= 1


@pytest.mark.asyncio
async def test_run_agent_respects_max_depth_zero():
    config = AgentConfig(max_depth=0)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_add_url_response("https://cafef.vn/article.chn")
        )
        state = await run_agent("https://cafef.vn", config)
    # depth-1 URLs should have been blocked — only seed visited
    assert all("cafef.vn/article" not in url for url in state.visited)


@pytest.mark.asyncio
async def test_run_agent_same_domain_blocks_off_domain():
    config = AgentConfig(same_domain=True)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_add_url_response("https://vneconomy.vn/other.chn")
        )
        state = await run_agent("https://cafef.vn", config)
    assert all("vneconomy.vn" not in url for url in state.visited)


@pytest.mark.asyncio
async def test_run_agent_tokens_used_equals_sum():
    config = AgentConfig(max_pages=1)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        state = await run_agent("https://cafef.vn", config)
    assert state.tokens_used == state.total_input_tokens + state.total_output_tokens


@pytest.mark.asyncio
async def test_run_agent_exits_when_token_budget_exceeded():
    config = AgentConfig(token_budget=1)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        state = await run_agent("https://cafef.vn", config)
    # After first Claude call tokens_used > 1, loop should have stopped
    assert state.tokens_used > 0


@pytest.mark.asyncio
async def test_run_agent_invalid_url_returns_empty_pages(caplog):
    config = AgentConfig()
    failed = _page(success=False)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=failed)),
        patch("src.agent.anthropic.AsyncAnthropic"),
        caplog.at_level(logging.WARNING, logger="src.agent"),
    ):
        state = await run_agent("https://invalid.xyz", config)
    assert state.pages == []
    assert any("fetch failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_run_agent_finish_tool_sets_finish_reason():
    config = AgentConfig(max_pages=5)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        state = await run_agent("https://cafef.vn", config)
    assert state.finished is True
    assert state.finish_reason == "goal satisfied"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_logs_fetch_at_info(caplog):
    config = AgentConfig(max_pages=1)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
        caplog.at_level(logging.INFO, logger="src.agent"),
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    assert any("fetching" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_run_agent_logs_finish_reason_at_info(caplog):
    config = AgentConfig(max_pages=5)
    with (
        patch("src.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("src.agent.anthropic.AsyncAnthropic") as mock_cls,
        caplog.at_level(logging.INFO, logger="src.agent"),
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    assert any("agent finished" in r.message for r in caplog.records)
