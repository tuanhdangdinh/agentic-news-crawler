"""Tests for src/crawler.py — fetch_page."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.crawler import fetch_page


def _crawler_context(result: MagicMock) -> MagicMock:
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=result)
    return crawler


def _crawl_result(success: bool = True) -> MagicMock:
    markdown = MagicMock()
    markdown.fit_markdown = "Filtered markdown"
    markdown.raw_markdown = "Raw markdown"

    result = MagicMock()
    result.success = success
    result.status_code = 200 if success else 500
    result.error_message = None if success else "server error"
    result.url = "https://cafef.vn/article.chn"
    result.markdown = markdown
    result.html = "<html></html>"
    result.links = {
        "internal": [{"href": "https://cafef.vn/internal.chn"}],
        "external": [{"href": "https://example.com/external"}],
    }
    result.metadata = {"title": "CafeF article"}
    result.response_headers = {"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"}
    return result


@pytest.mark.asyncio
async def test_fetch_page_returns_page_result_on_success():
    result = _crawl_result()
    crawler = _crawler_context(result)
    with patch("src.crawler.AsyncWebCrawler", return_value=crawler):
        page = await fetch_page("https://cafef.vn/article.chn")
    assert page.success is True
    assert page.status_code == 200
    assert page.title == "CafeF article"
    assert page.markdown == "Filtered markdown"
    assert page.raw_markdown == "Raw markdown"
    assert page.html == "<html></html>"
    assert page.links_internal == ["https://cafef.vn/internal.chn"]
    assert page.links_external == ["https://example.com/external"]
    assert page.headers == {"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"}


@pytest.mark.asyncio
async def test_fetch_page_retries_on_500_then_returns_failure():
    result = _crawl_result(success=False)
    crawler = _crawler_context(result)
    mock_sleep = AsyncMock()
    with (
        patch("src.crawler.AsyncWebCrawler", return_value=crawler),
        patch("src.crawler.asyncio.sleep", mock_sleep),
    ):
        page = await fetch_page("https://cafef.vn/article.chn")
    assert page.success is False
    assert page.status_code == 500
    assert page.error == "server error"
    assert crawler.arun.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_fetch_page_retries_on_exception_then_returns_failure():
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(side_effect=Exception("browser failed"))
    mock_sleep = AsyncMock()
    with (
        patch("src.crawler.AsyncWebCrawler", return_value=crawler),
        patch("src.crawler.asyncio.sleep", mock_sleep),
    ):
        page = await fetch_page("https://cafef.vn/article.chn")
    assert page.success is False
    assert page.status_code is None
    assert page.error == "browser failed"
    assert crawler.arun.call_count == 3
    assert mock_sleep.call_count == 2
