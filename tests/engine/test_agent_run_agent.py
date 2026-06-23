"""Tests for src/agent.py — run_agent."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawl_tool.engine.agent import AgentConfig, CrawlState, run_agent
from crawl_tool.engine.models import PageResult

_INFERRED_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}


def _article_page(url: str = "https://cafef.vn/gia-vang-188260603074758376.chn") -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=200,
        title="Article",
        markdown="Article content about gold prices",
        links_internal=[],
        metadata={"article:published_time": "2026-06-03T09:16:00+07:00"},
        success=True,
        error=None,
    )


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


@pytest.mark.asyncio
async def test_run_agent_infers_schema_once_before_loop():
    config = AgentConfig(
        goal="collect news",
        max_pages=1,
        extract_prompt="extract title",
        extract_schema=None,
    )
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        patch(
            "crawl_tool.engine.agent.infer_schema", AsyncMock(return_value=_INFERRED_SCHEMA)
        ) as mock_infer,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    mock_infer.assert_called_once()
    assert config.extract_schema == _INFERRED_SCHEMA


@pytest.mark.asyncio
async def test_run_agent_uses_registered_schema_before_inference():
    config = AgentConfig(
        goal="collect news",
        max_pages=1,
        extract_prompt="extract stock tickers and key financial figures",
    )
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        patch("crawl_tool.engine.agent.infer_schema", AsyncMock()) as mock_infer,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)

    mock_infer.assert_not_called()
    assert config.extract_schema is not None
    assert config.extract_schema["properties"]["key_financial_figures"]["items"]["type"] == "object"


@pytest.mark.asyncio
async def test_run_agent_skips_infer_schema_when_schema_provided():
    config = AgentConfig(
        goal="collect news",
        max_pages=1,
        extract_prompt="extract key financial figures",
        extract_schema=_INFERRED_SCHEMA,
    )
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        patch(
            "crawl_tool.engine.agent.infer_schema", AsyncMock(return_value=_INFERRED_SCHEMA)
        ) as mock_infer,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    mock_infer.assert_not_called()
    assert config.extract_schema == _INFERRED_SCHEMA


@pytest.mark.asyncio
async def test_run_agent_stores_depth_in_page_metadata():
    config = AgentConfig(goal="collect news", max_pages=1)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
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
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
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
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
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
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
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
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
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
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        state = await run_agent("https://cafef.vn", config)
    assert state.tokens_used == state.total_input_tokens + state.total_output_tokens


@pytest.mark.asyncio
async def test_run_agent_exits_when_token_budget_exceeded():
    # Claude adds a URL so the frontier stays non-empty; the second iteration
    # hits the budget guard (150 tokens used > budget 1) before fetching again.
    config = AgentConfig(token_budget=1)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_add_url_response("https://cafef.vn/article-1.chn")
        )
        state = await run_agent("https://cafef.vn", config)
    assert state.stop_reason == "token_budget"


@pytest.mark.asyncio
async def test_run_agent_skips_failed_page_fetch(caplog):
    config = AgentConfig()
    failed = _page(success=False)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=failed)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic"),
        caplog.at_level(logging.WARNING, logger="crawl_tool.engine.agent"),
    ):
        state = await run_agent("https://invalid.xyz", config)
    assert state.pages == []
    assert any("fetch failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_run_agent_finish_tool_sets_finish_reason():
    config = AgentConfig(max_pages=5)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        state = await run_agent("https://cafef.vn", config)
    assert state.finished is True
    assert state.finish_reason == "goal satisfied"


@pytest.mark.asyncio
async def test_run_agent_logs_fetch_at_info(caplog):
    config = AgentConfig(max_pages=1)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        caplog.at_level(logging.INFO, logger="crawl_tool.engine.agent"),
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    assert any("fetching" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_run_agent_logs_page_status_depth_and_fetch_time(caplog):
    config = AgentConfig(max_pages=1)
    page = _page()
    page.fetch_time = 0.25
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=page)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        caplog.at_level(logging.INFO, logger="crawl_tool.engine.agent"),
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    payload = next(
        json.loads(record.message)
        for record in caplog.records
        if json.loads(record.message).get("event") == "page collected"
    )
    assert payload["url"] == "https://cafef.vn"
    assert payload["status"] == 200
    assert payload["depth"] == 0
    assert payload["fetch_time"] == 0.25


@pytest.mark.asyncio
async def test_run_agent_logs_finish_reason_at_info(caplog):
    config = AgentConfig(max_pages=5)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        caplog.at_level(logging.INFO, logger="crawl_tool.engine.agent"),
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    assert any("agent finished" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_run_agent_date_filter_drops_out_of_range_article():
    config = AgentConfig(date_filter="2026-06-01", include_undated=False)
    # article page dated 2026-06-03 but filter is exactly 2026-06-01 → out of range
    old_article = _article_page()
    old_article.metadata["article:published_time"] = "2026-05-01T00:00:00Z"
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=old_article)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic"),
    ):
        state = await run_agent(old_article.url, config)
    assert state.pages == []


@pytest.mark.asyncio
async def test_run_agent_date_filter_keeps_in_range_article():
    config = AgentConfig(date_filter="2026-06-03", include_undated=False)
    article = _article_page()  # has article:published_time = 2026-06-03
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=article)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        state = await run_agent(article.url, config)
    assert len(state.pages) == 1


@pytest.mark.asyncio
async def test_run_agent_date_filter_excludes_undated_article_by_default():
    article = _article_page()
    article.url = "https://example.com/very-long-undated-economy-article-slug.html"
    article.final_url = article.url
    article.metadata.clear()
    config = AgentConfig(date_filter="2026-06-03", include_undated=False)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=article)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic"),
    ):
        state = await run_agent(article.url, config)
    assert state.pages == []


@pytest.mark.asyncio
async def test_run_agent_date_filter_includes_undated_article_when_enabled():
    article = _article_page()
    article.url = "https://example.com/very-long-undated-economy-article-slug.html"
    article.final_url = article.url
    article.metadata.clear()
    config = AgentConfig(date_filter="2026-06-03", include_undated=True)
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=article)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        state = await run_agent(article.url, config)
    assert len(state.pages) == 1


@pytest.mark.asyncio
async def test_run_agent_date_filter_does_not_drop_navigation_pages():
    config = AgentConfig(date_filter="2026-06-01", include_undated=False)
    # _page() has no date and is not an article page — should not be dropped
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        state = await run_agent("https://cafef.vn", config)
    assert len(state.pages) == 1


@pytest.mark.asyncio
async def test_run_agent_auto_extracts_from_article_pages():
    article = _article_page()
    extracted = {"title": "Gold prices rise"}
    config = AgentConfig(
        extract_prompt="extract title",
        extract_schema=_INFERRED_SCHEMA,
    )
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=article)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        patch(
            "crawl_tool.engine.agent.extractor_extract", AsyncMock(return_value=extracted)
        ) as mock_extract,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        state = await run_agent(article.url, config)
    mock_extract.assert_called_once()
    assert mock_extract.call_args.kwargs.get("lenient") is False
    assert state.pages[0].metadata.get("extracted") == extracted


@pytest.mark.asyncio
async def test_run_agent_auto_extract_is_lenient_for_inferred_schema():
    article = _article_page()
    config = AgentConfig(
        extract_prompt="extract title",
        extract_schema=None,
    )
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=article)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
        patch("crawl_tool.engine.agent.infer_schema", AsyncMock(return_value=_INFERRED_SCHEMA)),
        patch(
            "crawl_tool.engine.agent.extractor_extract", AsyncMock(return_value={"title": "x"})
        ) as mock_extract,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        await run_agent(article.url, config)
    assert config.extract_schema_inferred is True
    assert mock_extract.call_args.kwargs.get("lenient") is True


@pytest.mark.asyncio
async def test_run_agent_max_chars_truncates_markdown_sent_to_claude():
    """max_chars > 0 must limit the markdown sent to Claude, not the stored page."""
    long_page = _page()
    long_page.markdown = "x" * 20_000
    config = AgentConfig(max_pages=1, max_chars=500)

    captured_calls: list[dict] = []

    async def fake_create(**kwargs):
        captured_calls.append(kwargs)
        return _finish_response()

    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=long_page)),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = fake_create
        state = await run_agent("https://cafef.vn", config)

    assert len(state.pages[0].markdown) == 20_000, "stored markdown must not be truncated"
    user_msg = captured_calls[0]["messages"][0]["content"]
    assert "x" * 501 not in user_msg, "Claude should not receive more than max_chars"


@pytest.mark.asyncio
async def test_run_agent_passes_css_selector_to_fetch_page():
    config = AgentConfig(max_pages=1, css_selector="article.main")
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())) as mock_fetch,
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_finish_response())
        await run_agent("https://cafef.vn", config)
    mock_fetch.assert_called_once_with(
        "https://cafef.vn", css_selector="article.main", proxy_rotator=None
    )


@pytest.mark.asyncio
async def test_run_agent_uses_injected_state():
    config = AgentConfig(goal="collect news", max_pages=1)
    injected = CrawlState()
    with (
        patch("crawl_tool.engine.agent.fetch_page", AsyncMock(return_value=_page())),
        patch("crawl_tool.engine.agent.anthropic.AsyncAnthropic") as mock_cls,
    ):
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_end_turn_response())
        returned = await run_agent("https://cafef.vn", config, state=injected)
    assert returned is injected
    assert len(injected.pages) == 1
