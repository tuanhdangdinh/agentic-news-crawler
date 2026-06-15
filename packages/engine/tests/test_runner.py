"""Tests for crawl_engine.runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from crawl_engine.agent import CrawlState
from crawl_engine.contract import CrawlRequest
from crawl_engine.models import PageResult
from crawl_engine.runner import execute


def _page(url: str = "https://cafef.vn", success: bool = True) -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=200 if success else 500,
        title="CafeF",
        markdown="Economy news",
        links_internal=[],
        success=success,
        error=None if success else "boom",
    )


@pytest.mark.asyncio
async def test_execute_direct_fetch_when_no_goal_or_extract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PROXY_URL", raising=False)
    request = CrawlRequest(seed_url="https://cafef.vn", css_selector=".article-body")
    with patch("crawl_engine.runner.fetch_page", AsyncMock(return_value=_page())) as mock_fetch:
        payload = await execute(request, CrawlState())
    mock_fetch.assert_awaited_once_with(
        "https://cafef.vn",
        css_selector=".article-body",
        proxy_session=None,
    )
    assert payload["meta"]["total_pages"] == 1
    assert payload["meta"]["finish_reason"] == "single page fetched"
    assert payload["pages"][0]["url"] == "https://cafef.vn"


@pytest.mark.asyncio
async def test_execute_runs_agent_and_fills_injected_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PROXY_URL", raising=False)
    request = CrawlRequest(
        seed_url="https://cafef.vn",
        goal="collect news",
        max_depth=3,
        max_pages=7,
    )
    state = CrawlState()

    async def fake_run_agent(seed, config, state=None, *, proxy_session=None):
        state.pages.append(_page())
        state.finish_reason = "done"
        return state

    with patch("crawl_engine.runner.run_agent", side_effect=fake_run_agent) as mock_run:
        payload = await execute(request, state)
    mock_run.assert_awaited_once()
    seed, config = mock_run.await_args.args
    assert seed == "https://cafef.vn"
    assert config.goal == "collect news"
    assert config.max_depth == 3
    assert config.max_pages == 7
    assert mock_run.await_args.kwargs["state"] is state
    assert mock_run.await_args.kwargs["proxy_session"] is None
    assert payload["meta"]["pages_collected"] == 1
    assert payload["meta"]["seed_url"] == "https://cafef.vn"


@pytest.mark.asyncio
async def test_execute_snapshots_agent_state_lists(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PROXY_URL", raising=False)
    request = CrawlRequest(seed_url="https://cafef.vn", goal="collect news")
    state = CrawlState()

    async def fake_run_agent(seed, config, state=None, *, proxy_session=None):
        state.article_pages.append("https://cafef.vn/article")
        state.frontier_at_finish.append("https://cafef.vn/next")
        return state

    with patch("crawl_engine.runner.run_agent", side_effect=fake_run_agent):
        payload = await execute(request, state)

    state.article_pages.append("https://cafef.vn/later")
    state.frontier_at_finish.append("https://cafef.vn/later-next")

    assert payload["meta"]["article_pages"] == ["https://cafef.vn/article"]
    assert payload["meta"]["frontier_at_finish"] == ["https://cafef.vn/next"]


@pytest.mark.asyncio
async def test_execute_excludes_html_and_raw_markdown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PROXY_URL", raising=False)
    request = CrawlRequest(seed_url="https://cafef.vn")
    page = _page()
    page.html = "<html></html>"
    page.raw_markdown = "raw"
    with patch("crawl_engine.runner.fetch_page", AsyncMock(return_value=page)):
        payload = await execute(request, CrawlState())
    assert "html" not in payload["pages"][0]
    assert "raw_markdown" not in payload["pages"][0]


@pytest.mark.asyncio
async def test_execute_passes_managed_proxy_session_when_proxy_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROXY_URL", "http://proxy.example.com:8080")
    monkeypatch.setenv("PROXY_PASSWORD", "secret")

    captured: dict = {}

    async def fake_run_agent(seed, config, state=None, *, proxy_session=None):
        captured["proxy_session"] = proxy_session
        state.pages.append(_page())
        state.finish_reason = "done"

    request = CrawlRequest(seed_url="https://cafef.vn", goal="collect news")
    with patch("crawl_engine.runner.run_agent", side_effect=fake_run_agent):
        await execute(request, CrawlState())

    from crawl_engine.proxy import ManagedProxySession

    assert isinstance(captured.get("proxy_session"), ManagedProxySession)


@pytest.mark.asyncio
async def test_execute_no_proxy_session_when_proxy_url_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROXY_URL", raising=False)

    captured: dict = {}

    async def fake_run_agent(seed, config, state=None, *, proxy_session=None):
        captured["proxy_session"] = proxy_session
        state.pages.append(_page())
        state.finish_reason = "done"

    request = CrawlRequest(seed_url="https://cafef.vn", goal="collect news")
    with patch("crawl_engine.runner.run_agent", side_effect=fake_run_agent):
        await execute(request, CrawlState())

    assert captured.get("proxy_session") is None
