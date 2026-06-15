"""Tests for src/crawler.py — fetch_page and article_selector_for_url."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crawl_engine.crawler import (
    _extract_byline_author,
    article_selector_for_url,
    article_target_elements_for_url,
    fetch_page,
    looks_like_article_url,
)


def _crawler_context(result: MagicMock) -> MagicMock:
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(return_value=result)
    return crawler


def _crawl_result(
    success: bool = True,
    markdown: str = "Filtered markdown " * 20,
    raw_markdown: str = "Raw markdown",
    status_code: int | None = None,
) -> MagicMock:
    md = MagicMock()
    md.fit_markdown = markdown
    md.raw_markdown = raw_markdown

    result = MagicMock()
    result.success = success
    result.status_code = status_code if status_code is not None else (200 if success else 500)
    result.error_message = None if success else "server error"
    result.url = "https://cafef.vn/bai-viet-123456789.chn"
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
        (
            "https://vneconomy.vn/blue-chips-phuc-hoi-vn-index-quay-dau-tang-tu-nguong-ho-tro.htm",
            ".block-detail-page",
        ),
        ("https://cafef.vn", None),
        ("https://cafef.vn/tai-chinh-ngan-hang.chn", None),
        ("https://tuoitre.vn/kinh-doanh.htm", None),
        ("https://example.com/article.html", None),
    ],
)
def test_article_selector_for_url(url: str, expected: str | None):
    assert article_selector_for_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://vietnamnews.vn/economy/1782728/global-rubber-prices-surge.html", True),
        (
            "https://nhandan.vn/gia-vang-ngay-56-trong-nuoc-lao-doc-phien-thu-5-lien-tiep-rut-ngan-chenh-lech-so-gia-the-gioi-post967192.html",
            True,
        ),
        ("https://www.vietnamplus.vn/ngan-hang-the-gioi-kinh-te-viet-nam-post1114632.vnp", True),
        ("https://example.com/world/economy-growth-slows-in-asia-20260605000123.htm", True),
        ("https://example.com/very-long-economy-news-article-slug-with-many-words.html", True),
        ("https://vietnamnews.vn/economy", False),
        ("https://www.vietnamplus.vn/kinhte.vnp", False),
        ("https://example.com/article.html", False),
    ],
)
def test_looks_like_article_url(url: str, expected: bool):
    assert looks_like_article_url(url) is expected


def test_article_target_elements_for_url_prefers_known_selector():
    assert article_target_elements_for_url("https://cafef.vn/bai-viet-123456789.chn") == [
        ".detail-content"
    ]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://nhandan.vn/gia-vang-ngay-56-trong-nuoc-lao-doc-phien-thu-5-lien-tiep-rut-ngan-chenh-lech-so-gia-the-gioi-post967192.html",
            [".main-col.content-col"],
        ),
        (
            "https://baodautu.vn/nen-kinh-te-duy-tri-suc-chong-chiu-ben-bi-vuot-thach-thuc-d611681.html",
            [".col630.ml-auto.mb40"],
        ),
        (
            "https://www.vietnamplus.vn/ngan-hang-the-gioi-kinh-te-viet-nam-post1114632.vnp",
            [
                ".article__title",
                ".article__sapo",
                ".article__meta",
                ".article__body.zce-content-body.cms-body",
            ],
        ),
    ],
)
def test_article_target_elements_for_url_prefers_domain_targets(
    url: str,
    expected: list[str],
):
    assert article_target_elements_for_url(url) == expected


def test_article_target_elements_for_url_uses_generic_targets_for_unknown_article():
    targets = article_target_elements_for_url(
        "https://vietnamnews.vn/economy/1782728/global-rubber-prices-surge.html"
    )
    assert "#abody" in targets
    assert ".detail .headline" in targets
    assert ".detail__meta" in targets
    assert ".title-detail" in targets
    assert ".author-share-top" in targets
    assert ".author-detail" in targets
    assert ".byline" in targets
    assert ".sapo" in targets
    assert ".sapo_detail" in targets
    assert ".article-content" in targets


def test_article_target_elements_for_url_returns_empty_for_listing_page():
    assert article_target_elements_for_url("https://vietnamnews.vn/economy") == []


def test_extract_byline_author_normalizes_explicit_byline():
    html = '<html><body><p class="author-detail __MB_AUTHOR">By Ngan Ha</p></body></html>'
    assert _extract_byline_author(html) == "Ngan Ha"


def test_extract_byline_author_normalizes_generic_author_with_email_or_date():
    html = """
    <html><body>
        <p class="author">Mai Phương - maiphuongthanhnien@gmail.com</p>
        <p class="author-share-top">Hà Nguyễn - 05/06/2026 08:03</p>
    </body></html>
    """
    assert _extract_byline_author(html) == "Mai Phương"


def test_extract_byline_author_rejects_missing_byline():
    html = "<html><body><p>Dr. Baaziz Achour spoke with VIR's My Kieu.</p></body></html>"
    assert _extract_byline_author(html) is None


# ---------------------------------------------------------------------------
# fetch_page — basic success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_page_returns_page_result_on_success():
    result = _crawl_result()
    result.html = '<html><body><p class="author-detail">By Ngan Ha</p></body></html>'
    crawler = _crawler_context(result)
    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
        page = await fetch_page("https://cafef.vn/bai-viet-123456789.chn")
    assert page.success is True
    assert page.status_code == 200
    assert page.title == "CafeF article"
    assert page.markdown == "Filtered markdown " * 20
    assert page.raw_markdown == "Raw markdown"
    assert page.html == '<html><body><p class="author-detail">By Ngan Ha</p></body></html>'
    assert page.links_internal == ["https://cafef.vn/internal.chn"]
    assert page.links_external == ["https://example.com/external"]
    assert page.headers == {"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"}
    assert page.metadata["byline_author"] == "Ngan Ha"


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
    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
        await fetch_page("https://cafef.vn/bai-viet-123456789.chn")

    assert captured_cfgs[0].target_elements == [".detail-content"]
    assert getattr(captured_cfgs[0], "css_selector", None) is None
    assert captured_cfgs[0].excluded_tags == ["script", "style", "noscript", "form"]
    assert captured_cfgs[0].remove_forms is True
    assert captured_cfgs[0].remove_overlay_elements is True
    assert captured_cfgs[0].markdown_generator.options == {"ignore_links": True}


@pytest.mark.asyncio
async def test_fetch_page_uses_generic_target_elements_for_unknown_article_url():
    """Unknown article-looking URLs get generic markdown target_elements."""
    result = _crawl_result()
    crawler = _crawler_context(result)
    captured_cfgs: list = []

    async def capture_arun(url, config):
        captured_cfgs.append(config)
        return result

    crawler.arun = capture_arun
    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
        await fetch_page("https://vietnamnews.vn/economy/1782728/global-rubber-prices-surge.html")

    assert "#abody" in captured_cfgs[0].target_elements
    assert ".detail .headline" in captured_cfgs[0].target_elements
    assert ".detail__meta" in captured_cfgs[0].target_elements
    assert ".author-detail" in captured_cfgs[0].target_elements
    assert ".byline" in captured_cfgs[0].target_elements
    assert ".sapo" in captured_cfgs[0].target_elements
    assert ".article-content" in captured_cfgs[0].target_elements
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
    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
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
    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
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
    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
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

    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
        page = await fetch_page("https://cafef.vn/bai-viet-123456789.chn")

    assert call_count == 2
    assert captured_cfgs[0].target_elements == [".detail-content"]
    assert getattr(captured_cfgs[1], "css_selector", None) is None
    assert not getattr(captured_cfgs[1], "target_elements", None)
    assert page.markdown == "Full article body"


@pytest.mark.asyncio
async def test_fetch_page_falls_back_to_full_page_when_scoped_markdown_too_short():
    """If scoped fetch returns only whitespace/noise, retry full-page."""
    scoped_result = _crawl_result(markdown="\n", raw_markdown="\n")
    full_result = _crawl_result(markdown="Full article body after near-empty scoped result")

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

    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
        page = await fetch_page("https://cafef.vn/bai-viet-123456789.chn")

    assert call_count == 2
    assert captured_cfgs[0].target_elements == [".detail-content"]
    assert getattr(captured_cfgs[1], "css_selector", None) is None
    assert not getattr(captured_cfgs[1], "target_elements", None)
    assert page.markdown == "Full article body after near-empty scoped result"


# ---------------------------------------------------------------------------
# fetch_page — retry on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_page_retries_three_times_on_500_then_returns_failure():
    result = _crawl_result(success=False)
    crawler = _crawler_context(result)
    mock_sleep = AsyncMock()
    with (
        patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler),
        patch("crawl_engine.crawler.asyncio.sleep", mock_sleep),
    ):
        page = await fetch_page("https://cafef.vn/article.chn")
    assert page.success is False
    assert page.status_code == 500
    assert page.error == "server error"
    assert crawler.arun.call_count == 4
    assert [call.args[0] for call in mock_sleep.await_args_list] == [1, 2, 4]


@pytest.mark.asyncio
async def test_fetch_page_treats_404_status_as_failure_even_when_crawl_succeeds():
    result = _crawl_result(success=True, status_code=404)
    crawler = _crawler_context(result)
    with patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler):
        page = await fetch_page("https://vneconomy.vn/missing.htm")
    assert page.success is False
    assert page.status_code == 404
    assert page.markdown == ""
    assert page.error == "HTTP 404"
    assert crawler.arun.call_count == 1


@pytest.mark.asyncio
async def test_fetch_page_retries_three_times_on_exception_then_returns_failure():
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(side_effect=Exception("browser failed"))
    mock_sleep = AsyncMock()
    with (
        patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler),
        patch("crawl_engine.crawler.asyncio.sleep", mock_sleep),
    ):
        page = await fetch_page("https://cafef.vn/article.chn")
    assert page.success is False
    assert page.status_code is None
    assert page.error == "browser failed"
    assert crawler.arun.call_count == 4
    assert [call.args[0] for call in mock_sleep.await_args_list] == [1, 2, 4]


@pytest.mark.asyncio
async def test_fetch_page_respects_retry_after_seconds():
    result = _crawl_result(success=False, status_code=429)
    result.response_headers = {"Retry-After": "180"}
    crawler = _crawler_context(result)
    mock_sleep = AsyncMock()
    with (
        patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler),
        patch("crawl_engine.crawler.asyncio.sleep", mock_sleep),
    ):
        await fetch_page("https://cafef.vn/article.chn")
    assert [call.args[0] for call in mock_sleep.await_args_list] == [180, 180, 180]


@pytest.mark.asyncio
async def test_fetch_page_respects_retry_after_http_date():
    now = datetime(2026, 6, 10, 4, 0, tzinfo=UTC)
    result = _crawl_result(success=False, status_code=429)
    result.response_headers = {"Retry-After": format_datetime(now + timedelta(seconds=90))}
    crawler = _crawler_context(result)
    mock_sleep = AsyncMock()
    with (
        patch("crawl_engine.crawler.AsyncWebCrawler", return_value=crawler),
        patch("crawl_engine.crawler.asyncio.sleep", mock_sleep),
        patch("crawl_engine.crawler.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = now
        await fetch_page("https://cafef.vn/article.chn")
    assert [call.args[0] for call in mock_sleep.await_args_list] == [90, 90, 90]


def test_user_agent_identifies_tool_and_contact():
    from crawl_engine.crawler import _BROWSER_CFG, USER_AGENT

    assert USER_AGENT.startswith("crawl-tool/")
    assert "@" in USER_AGENT
    assert _BROWSER_CFG.user_agent == USER_AGENT


# ---------------------------------------------------------------------------
# _is_captcha_response and _is_blocked helpers
# ---------------------------------------------------------------------------


def _blocked_result(
    status_code: int = 403,
    html: str = "",
    title: str = "Forbidden",
) -> MagicMock:
    result = MagicMock()
    result.success = False
    result.status_code = status_code
    result.error_message = f"HTTP {status_code}"
    result.url = "https://example.com"
    result.html = html
    result.metadata = {"title": title}
    result.response_headers = {}
    result.markdown = None
    result.links = {}
    return result


# --- _is_captcha_response ---


def test_captcha_cf_challenge_running() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(html='<div id="cf-challenge-running"></div>')
    assert _is_captcha_response(result) is True


def test_captcha_cf_browser_verification() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(html='<div class="cf-browser-verification"></div>')
    assert _is_captcha_response(result) is True


def test_captcha_cf_challenge_body() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(html='<div class="cf-challenge-body"></div>')
    assert _is_captcha_response(result) is True


def test_captcha_403_just_a_moment() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(status_code=403, title="Just a moment...")
    assert _is_captcha_response(result) is True


def test_captcha_403_verify_you_are_human() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(status_code=403, title="Verify you are human")
    assert _is_captcha_response(result) is True


def test_not_captcha_data_sitekey_alone() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(html='<form data-sitekey="abc123"><button>Submit</button></form>')
    assert _is_captcha_response(result) is False


def test_not_captcha_plain_403() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(status_code=403, html="<html>Forbidden</html>", title="Forbidden")
    assert _is_captcha_response(result) is False


def test_not_captcha_200_with_recaptcha_widget() -> None:
    from crawl_engine.crawler import _is_captcha_response

    result = _blocked_result(
        status_code=200,
        html='<div data-sitekey="key"><script src="recaptcha.net/api.js"></script></div>',
        title="Comment on post",
    )
    assert _is_captcha_response(result) is False


# --- _is_blocked ---


def test_is_blocked_403() -> None:
    from crawl_engine.crawler import _is_blocked

    assert _is_blocked(_blocked_result(403)) is True


def test_is_blocked_429() -> None:
    from crawl_engine.crawler import _is_blocked

    assert _is_blocked(_blocked_result(429)) is True


def test_is_blocked_captcha_200() -> None:
    from crawl_engine.crawler import _is_blocked

    result = _blocked_result(status_code=200, html='<div id="cf-challenge-running"></div>')
    assert _is_blocked(result) is True


def test_not_blocked_200() -> None:
    from crawl_engine.crawler import _is_blocked

    result = MagicMock()
    result.status_code = 200
    result.html = ""
    result.metadata = {}
    assert _is_blocked(result) is False


def test_not_blocked_500() -> None:
    from crawl_engine.crawler import _is_blocked

    result = _blocked_result(500)
    assert _is_blocked(result) is False


# ---------------------------------------------------------------------------
# proxy session dispatch — _fetch_managed_proxy
# ---------------------------------------------------------------------------

from crawl_engine.proxy import ManagedProxySession, ProxyCredentials, ProxySettings


def _make_proxy_session() -> MagicMock:
    """Mock ManagedProxySession returning fixed credentials with zero delay."""
    session = MagicMock(spec=ManagedProxySession)
    default = (
        ProxyCredentials(server="http://proxy:8080", username="user-abc123", password="pass"),
        0.0,
    )
    session.acquire_credentials = AsyncMock(return_value=default)
    session.rotate = AsyncMock()
    session.settings = ProxySettings(
        enabled=True,
        url="http://proxy:8080",
        username_template="user-session-{session_id}",
        password="pass",
        rotate_after_requests=20,
        domain_delay=0.0,
        block_backoff=0.0,
    )
    return session


def _multi_crawler(*results: MagicMock) -> MagicMock:
    """Crawler mock that returns successive results on each arun() call."""
    crawler = MagicMock()
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=None)
    crawler.arun = AsyncMock(side_effect=list(results))
    return crawler


@pytest.mark.asyncio
async def test_403_no_proxy_no_rotation() -> None:
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls:
        mock_cls.return_value = _crawler_context(_crawl_result(success=False, status_code=403))
        result = await fetch_page("https://example.com")
    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_403_with_proxy_rotates_once_then_succeeds() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _blocked_result(403),
            _crawl_result(),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="http_403")


@pytest.mark.asyncio
async def test_second_block_after_rotation_returns_proxy_blocked() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _blocked_result(403),
            _blocked_result(403),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is False
    assert result.error == "proxy_blocked"
    assert proxy.rotate.await_count == 1


@pytest.mark.asyncio
async def test_429_with_retry_after_rotates() -> None:
    proxy = _make_proxy_session()
    blocked = _blocked_result(429)
    blocked.response_headers = {"Retry-After": "5"}
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ) as mock_sleep:
        mock_cls.return_value = _multi_crawler(blocked, _crawl_result())
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="http_429")
    mock_sleep.assert_awaited()


@pytest.mark.asyncio
async def test_captcha_triggers_rotation() -> None:
    proxy = _make_proxy_session()
    captcha = _blocked_result(403, html='<div id="cf-challenge-running"></div>')
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(captcha, _crawl_result())
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="captcha")


@pytest.mark.asyncio
async def test_data_sitekey_alone_is_plain_403_not_captcha() -> None:
    proxy = _make_proxy_session()
    plain = _blocked_result(403, html='<form data-sitekey="key"></form>', title="Forbidden")
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(plain, _crawl_result())
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once_with("example.com", reason="http_403")


@pytest.mark.asyncio
async def test_5xx_uses_transient_retry_no_rotation() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _crawl_result(success=False, status_code=500),
            _crawl_result(),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_not_awaited()


@pytest.mark.asyncio
async def test_block_rotation_independent_of_transient_retries() -> None:
    """A 5xx transient retry followed by a 403 block still gets one rotation."""
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _multi_crawler(
            _crawl_result(success=False, status_code=500),
            _blocked_result(403),
            _crawl_result(),
        )
        result = await fetch_page("https://example.com", proxy_session=proxy)
    assert result.success is True
    proxy.rotate.assert_awaited_once()


@pytest.mark.asyncio
async def test_domain_delay_respected() -> None:
    """acquire_credentials returns wait > 0 on second domain call; fetch_page sleeps."""
    creds = ProxyCredentials(server="http://p:8080", username="u", password="pw")
    proxy = MagicMock(spec=ManagedProxySession)
    proxy.acquire_credentials = AsyncMock(side_effect=[(creds, 0.0), (creds, 1.5)])
    proxy.rotate = AsyncMock()
    proxy.settings = ProxySettings(
        enabled=True, url="http://p:8080", username_template="u-{session_id}",
        password="pw", rotate_after_requests=20, domain_delay=2.0, block_backoff=0.0,
    )
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ) as mock_sleep:
        mock_cls.return_value = _crawler_context(_crawl_result())
        await fetch_page("https://example.com", proxy_session=proxy)
        mock_cls.return_value = _crawler_context(_crawl_result())
        await fetch_page("https://example.com", proxy_session=proxy)
    assert any(call.args and call.args[0] == pytest.approx(1.5) for call in mock_sleep.await_args_list)


@pytest.mark.asyncio
async def test_page_result_contains_no_proxy_credentials() -> None:
    proxy = _make_proxy_session()
    with patch("crawl_engine.crawler.AsyncWebCrawler") as mock_cls, patch(
        "crawl_engine.crawler.asyncio.sleep"
    ):
        mock_cls.return_value = _crawler_context(_crawl_result())
        result = await fetch_page("https://cafef.vn/bai-viet-123456789.chn", proxy_session=proxy)
    result_dict = result.model_dump()
    assert "password" not in result_dict
    assert "proxy" not in str(result_dict).lower()
