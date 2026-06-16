"""Integration tests — end-to-end crawls on real Vietnamese economy sites.

Run with:
    uv run pytest -m integration

Excluded from the default pytest run because they require live internet access
and a valid ANTHROPIC_API_KEY.  Each test asserts the functional acceptance
criteria from the intern plan: crawl completion, depth correctness, dedup,
same-domain filter, date filter, and extraction accuracy.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
from crawl_tool.engine.agent import AgentConfig, run_agent
from crawl_tool.engine.crawler import fetch_page
from crawl_tool.engine.date_filter import detect_page_date, is_in_range

requires_anthropic_key = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY is required for agent integration tests",
)

# ---------------------------------------------------------------------------
# Site smoke tests — crawl completes, pages returned, no crashes
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_cafef_crawl_returns_pages():
    """Crawl CafeF seed page; agent collects at least one page without crashing."""
    config = AgentConfig(goal="collect economy news articles", max_depth=1, max_pages=3)
    state = await run_agent("https://cafef.vn", config)
    assert len(state.pages) >= 1
    assert all(p.success for p in state.pages)
    assert state.stop_reason in ("agent_finish", "max_pages", "frontier_empty", "token_budget")


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_vneconomy_crawl_returns_pages():
    """Crawl VnEconomy seed page; agent collects at least one page without crashing."""
    config = AgentConfig(goal="collect economy news articles", max_depth=1, max_pages=3)
    state = await run_agent("https://vneconomy.vn", config)
    assert len(state.pages) >= 1
    assert all(p.success for p in state.pages)


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_vietnamplus_crawl_returns_pages():
    """Crawl VietnamPlus economy section; agent collects at least one page."""
    config = AgentConfig(
        goal="collect economy and finance news",
        max_depth=1,
        max_pages=3,
    )
    state = await run_agent("https://www.vietnamplus.vn", config)
    assert len(state.pages) >= 1
    assert all(p.success for p in state.pages)


# ---------------------------------------------------------------------------
# Depth correctness — no depth-1 pages when max_depth=0
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_max_depth_zero_fetches_seed_only():
    """max_depth=0 fetches and visits only the seed URL."""
    seed_url = "https://cafef.vn"
    config = AgentConfig(goal="collect news", max_depth=0, max_pages=5)
    with patch("crawl_tool.engine.agent.fetch_page", wraps=fetch_page) as mock_fetch:
        state = await run_agent(seed_url, config)
    fetched_urls = [call.args[0] for call in mock_fetch.await_args_list]
    assert fetched_urls == [seed_url]
    assert state.visited == {seed_url}
    assert len(state.pages) == 1


# ---------------------------------------------------------------------------
# Deduplication — no URL fetched twice
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_no_duplicate_fetches():
    """The agent never calls fetch_page twice for the same URL."""
    config = AgentConfig(goal="collect economy news", max_depth=1, max_pages=5)
    with patch("crawl_tool.engine.agent.fetch_page", wraps=fetch_page) as mock_fetch:
        await run_agent("https://cafef.vn", config)
    fetched_urls = [call.args[0] for call in mock_fetch.await_args_list]
    assert len(fetched_urls) == len(set(fetched_urls))


# ---------------------------------------------------------------------------
# Same-domain filter — off-domain URLs must not appear when same_domain=True
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_same_domain_filter_keeps_crawl_on_seed_domain():
    """With same_domain=True (default), all visited URLs share the seed domain."""
    config = AgentConfig(goal="collect economy news", max_depth=1, max_pages=5, same_domain=True)
    state = await run_agent("https://cafef.vn", config)
    seed_domain = "cafef.vn"
    for url in state.visited:
        assert _normalized_host(url) == seed_domain, f"off-domain URL found: {url}"


# ---------------------------------------------------------------------------
# Date filter — pages outside range excluded on a site with known dates
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_date_filter_excludes_articles_outside_range():
    """Pages with a detectable date outside the filter range must not appear in state.pages."""
    today = date.today()
    from_date = today - timedelta(days=6)
    config = AgentConfig(
        goal="collect recent banking and stock market articles",
        date_filter="last 7 days",
        include_undated=False,
        max_depth=1,
        max_pages=5,
    )
    state = await run_agent("https://cafef.vn", config)
    article_urls = set(state.article_pages)
    dated_articles = []
    for page in state.pages:
        if page.final_url not in article_urls:
            continue
        page_date = detect_page_date(page)
        if page_date is not None:
            dated_articles.append((page, page_date))
    assert dated_articles, "crawl must collect at least one article with a detectable date"
    for page, page_date in dated_articles:
        assert is_in_range(page_date, from_date, today), (
            f"page outside date range in results: {page.final_url} date={page_date}"
        )


def _normalized_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


# ---------------------------------------------------------------------------
# Extraction accuracy — structured fields populated on article pages
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_extraction_populates_required_fields():
    """extract_prompt produces structured output with expected keys on article pages."""
    config = AgentConfig(
        goal="collect banking news articles",
        extract_prompt=(
            "extract the article title, publish date, author, and a one-sentence summary"
        ),
        max_depth=1,
        max_pages=3,
    )
    state = await run_agent("https://cafef.vn", config)
    extracted_pages = [p for p in state.pages if "extracted" in p.metadata]
    assert len(extracted_pages) >= 1, "at least one page must have extracted fields"
    for page in extracted_pages:
        result = page.metadata["extracted"]
        assert isinstance(result, dict), f"extracted must be a dict, got {type(result)}"
        required_fields = {"article_title", "publish_date", "author", "summary"}
        assert required_fields <= result.keys(), (
            f"missing extraction fields for {page.final_url}: "
            f"{sorted(required_fields - result.keys())}"
        )
        assert isinstance(result["article_title"], str) and result["article_title"].strip()
        assert isinstance(result["summary"], str) and result["summary"].strip()


# ---------------------------------------------------------------------------
# fetch_page smoke tests — site-level fetch without agent
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_fetch_vneconomy_returns_content():
    page = await fetch_page("https://vneconomy.vn")
    assert page.success
    assert page.status_code == 200
    assert len(page.markdown) > 100
    assert len(page.links_internal) > 0
    assert page.title is not None


@pytest.mark.integration
@pytest.mark.slow
async def test_fetch_vneconomy_section_returns_content():
    """Fetch a known VnEconomy section URL and verify content is extracted."""
    url = "https://vneconomy.vn/chung-khoan.htm"
    page = await fetch_page(url)
    assert page.success
    assert page.status_code == 200
    assert len(page.markdown) > 100


@pytest.mark.integration
@pytest.mark.slow
async def test_fetch_invalid_url_returns_failure():
    page = await fetch_page("https://this-domain-does-not-exist-xyz-123.com")
    assert not page.success
    assert page.error is not None
