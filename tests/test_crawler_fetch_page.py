"""Tests for src/crawler.py — fetch_page and article_selector_for_url."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.crawler import article_selector_for_url, fetch_page


def _crawler_context(result: MagicMock) -> MagicMock:
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=result)
    return crawler


def _crawl_result(
    success: bool = True,
    markdown: str = "Filtered markdown",
    raw_markdown: str = "Raw markdown",
) -> MagicMock:
    md = MagicMock()
    md.fit_markdown = markdown
    md.raw_markdown = raw_markdown

    result = MagicMock()
    result.success = success
    result.status_code = 200 if success else 500
    result.error_message = None if success else "server error"
    result.url = "https://cafef.vn/article.chn"
    result.markdown = md
    result.html = "<html></html>"
    result.links = {
        "internal": [{"href": "https://cafef.vn/internal.chn"}],
        "external": [{"href": "https://example.com/external"}],
    }
    result.metadata = {"title": "CafeF article"}
    result.response_headers = {"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"}
    return result


# ---------------------------------------------------------------------------
# article_selector_for_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://cafef.vn/bai-viet-123456789.chn", ".detail-content"),
        ("https://www.cafef.vn/bai-viet-123456789.chn", ".detail-content"),
        ("https://tuoitre.vn/tin-tuc-20260604161445695.htm", ".detail-content"),
        ("https://vneconomy.vn/blue-chips-phuc-hoi-vn-index-quay-dau-tang-tu-nguong-ho-tro.htm", ".block-detail-page"),
        ("https://cafef.vn", None),
        ("https://cafef.vn/tai-chinh-ngan-hang.chn", None),
        ("https://tuoitre.vn/kinh-doanh.htm", None),
        ("https://example.com/article.html", None),
    ],
)
def test_article_selector_for_url(url: str, expected: str | None):
    assert article_selector_for_url(url) == expected


# ---------------------------------------------------------------------------
# fetch_page — basic success
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# fetch_page — selector auto-detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_page_uses_target_elements_for_known_article_url():
    """CafeF article URLs scope markdown via target_elements, keeping metadata + links."""
    result = _crawl_result()
    crawler = _crawler_context(result)
    captured_cfgs: list = []

    async def capture_arun(url, config):
        captured_cfgs.append(config)
        return result

    crawler.arun = capture_arun
    with patch("src.crawler.AsyncWebCrawler", return_value=crawler):
        await fetch_page("https://cafef.vn/bai-viet-123456789.chn")

    assert captured_cfgs[0].target_elements == [".detail-content"]
    assert getattr(captured_cfgs[0], "css_selector", None) is None


@pytest.mark.asyncio
async def test_fetch_page_no_selector_for_homepage():
    """Homepage URLs must fetch the full page — no scoping at all."""
    result = _crawl_result()
    crawler = _crawler_context(result)
    captured_cfgs: list = []

    async def capture_arun(url, config):
        captured_cfgs.append(config)
        return result

    crawler.arun = capture_arun
    with patch("src.crawler.AsyncWebCrawler", return_value=crawler):
        await fetch_page("https://cafef.vn")

    assert getattr(captured_cfgs[0], "css_selector", None) is None
    assert not getattr(captured_cfgs[0], "target_elements", None)


@pytest.mark.asyncio
async def test_fetch_page_article_body_false_skips_auto_detection():
    """article_body=False must fetch the full page even for article URLs."""
    result = _crawl_result()
    crawler = _crawler_context(result)
    captured_cfgs: list = []

    async def capture_arun(url, config):
        captured_cfgs.append(config)
        return result

    crawler.arun = capture_arun
    with patch("src.crawler.AsyncWebCrawler", return_value=crawler):
        await fetch_page("https://cafef.vn/bai-viet-123456789.chn", article_body=False)

    assert getattr(captured_cfgs[0], "css_selector", None) is None
    assert not getattr(captured_cfgs[0], "target_elements", None)


@pytest.mark.asyncio
async def test_fetch_page_explicit_css_selector_hard_scopes():
    """An explicit css_selector must hard-scope, ignoring article-body auto-detection."""
    result = _crawl_result()
    crawler = _crawler_context(result)
    captured_cfgs: list = []

    async def capture_arun(url, config):
        captured_cfgs.append(config)
        return result

    crawler.arun = capture_arun
    with patch("src.crawler.AsyncWebCrawler", return_value=crawler):
        await fetch_page("https://cafef.vn/bai-viet-123456789.chn", css_selector=".custom")

    assert captured_cfgs[0].css_selector == ".custom"
    assert not getattr(captured_cfgs[0], "target_elements", None)


# ---------------------------------------------------------------------------
# fetch_page — empty-scoped fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_page_falls_back_to_full_page_when_scoped_markdown_empty():
    """If scoped fetch succeeds but returns empty markdown, retry full-page."""
    scoped_result = _crawl_result(markdown="", raw_markdown="")
    full_result = _crawl_result(markdown="Full article body")

    call_count = 0
    captured_cfgs: list = []

    async def arun_side_effect(url, config):
        nonlocal call_count
        captured_cfgs.append(config)
        call_count += 1
        return scoped_result if call_count == 1 else full_result

    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = arun_side_effect

    with patch("src.crawler.AsyncWebCrawler", return_value=crawler):
        page = await fetch_page("https://cafef.vn/bai-viet-123456789.chn")

    assert call_count == 2
    assert captured_cfgs[0].target_elements == [".detail-content"]
    assert getattr(captured_cfgs[1], "css_selector", None) is None
    assert not getattr(captured_cfgs[1], "target_elements", None)
    assert page.markdown == "Full article body"


# ---------------------------------------------------------------------------
# fetch_page — retry on failure
# ---------------------------------------------------------------------------

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
