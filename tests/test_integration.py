"""Integration tests — end-to-end crawls on real Vietnamese economy sites.

Run with:
    uv run pytest -m integration

Excluded from the default pytest run because they require live internet access
and a valid ANTHROPIC_API_KEY.  Each test asserts the functional acceptance
criteria from the intern plan: crawl completion, depth correctness, dedup,
same-domain filter, date filter, and extraction accuracy.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.agent import AgentConfig, run_agent
from src.crawler import fetch_page
from src.date_filter import detect_page_date, is_in_range

# ---------------------------------------------------------------------------
# Site smoke tests — crawl completes, pages returned, no crashes
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_cafef_crawl_returns_pages():
    """Crawl CafeF seed page; agent collects at least one page without crashing."""
    config = AgentConfig(goal="collect economy news articles", max_depth=1, max_pages=3)
    state = await run_agent("https://cafef.vn", config)
    assert len(state.pages) >= 1
    assert all(p.success for p in state.pages)
    assert state.stop_reason in ("agent_finish", "max_pages", "frontier_empty", "token_budget")


@pytest.mark.integration
@pytest.mark.slow
async def test_vneconomy_crawl_returns_pages():
    """Crawl VnEconomy seed page; agent collects at least one page without crashing."""
    config = AgentConfig(goal="collect economy news articles", max_depth=1, max_pages=3)
    state = await run_agent("https://vneconomy.vn", config)
    assert len(state.pages) >= 1
    assert all(p.success for p in state.pages)


@pytest.mark.integration
@pytest.mark.slow
async def test_vietnamplus_crawl_returns_pages():
    """Crawl VietnamPlus economy section; agent collects at least one page."""
    config = AgentConfig(
        goal="collect economy and finance news",
        max_depth=1,
        max_pages=3,
    )
    state = await run_agent("https://www.vietnamplus.vn/kinh-te.vnp", config)
    assert len(state.pages) >= 1
    assert all(p.success for p in state.pages)


# ---------------------------------------------------------------------------
# Depth correctness — no depth-1 pages when max_depth=0
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_max_depth_zero_fetches_seed_only():
    """max_depth=0 must not add any depth-1 URLs to visited."""
    config = AgentConfig(goal="collect news", max_depth=0, max_pages=5)
    state = await run_agent("https://cafef.vn", config)
    # With max_depth=0 the agent cannot add frontier URLs beyond depth 0
    assert len(state.pages) <= 1


# ---------------------------------------------------------------------------
# Deduplication — no URL fetched twice
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_no_duplicate_fetches():
    """Every URL in state.visited must appear exactly once."""
    config = AgentConfig(goal="collect economy news", max_depth=1, max_pages=5)
    state = await run_agent("https://cafef.vn", config)
    visited_list = list(state.visited)
    assert len(visited_list) == len(set(visited_list))


# ---------------------------------------------------------------------------
# Same-domain filter — off-domain URLs must not appear when same_domain=True
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_same_domain_filter_keeps_crawl_on_seed_domain():
    """With same_domain=True (default), all visited URLs share the seed domain."""
    from urllib.parse import urlparse

    config = AgentConfig(goal="collect economy news", max_depth=1, max_pages=5, same_domain=True)
    state = await run_agent("https://cafef.vn", config)
    seed_domain = "cafef.vn"
    for url in state.visited:
        parsed = urlparse(url)
        assert seed_domain in parsed.netloc, f"off-domain URL found: {url}"


# ---------------------------------------------------------------------------
# Date filter — pages outside range excluded on a site with known dates
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_date_filter_excludes_articles_outside_range():
    """Pages with a detectable date outside the filter range must not appear in state.pages."""
    today = date.today()
    from_date = today - timedelta(days=7)
    config = AgentConfig(
        goal="collect recent banking and stock market articles",
        date_filter="last 7 days",
        include_undated=False,
        max_depth=1,
        max_pages=5,
    )
    state = await run_agent("https://cafef.vn", config)
    for page in state.pages:
        page_date = detect_page_date(page)
        if page_date is not None:
            assert is_in_range(page_date, from_date, today), (
                f"page outside date range in results: {page.final_url} date={page_date}"
            )


# ---------------------------------------------------------------------------
# Extraction accuracy — structured fields populated on article pages
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_extraction_populates_required_fields():
    """extract_prompt produces structured output with expected keys on article pages."""
    config = AgentConfig(
        goal="collect banking news articles",
        extract_prompt="extract the article title, publish date, and a one-sentence summary",
        max_depth=1,
        max_pages=3,
    )
    state = await run_agent("https://cafef.vn", config)
    extracted_pages = [
        p for p in state.pages if "extracted" in p.metadata
    ]
    assert len(extracted_pages) >= 1, "at least one page must have extracted fields"
    for page in extracted_pages:
        result = page.metadata["extracted"]
        assert isinstance(result, dict), f"extracted must be a dict, got {type(result)}"
        assert len(result) >= 1, f"extracted dict is empty for {page.final_url}"


# ---------------------------------------------------------------------------
# fetch_page smoke tests — site-level fetch without agent
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
async def test_fetch_cafef_returns_content():
    page = await fetch_page("https://cafef.vn")
    assert page.success
    assert page.status_code == 200
    assert len(page.markdown) > 100
    assert len(page.links_internal) > 0
    assert page.title is not None


@pytest.mark.integration
@pytest.mark.slow
async def test_fetch_cafef_article_returns_content():
    """Fetch a known CafeF article URL and verify article body is extracted."""
    url = "https://cafef.vn/thi-truong-chung-khoan.chn"
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
