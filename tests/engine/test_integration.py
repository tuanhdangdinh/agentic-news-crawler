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
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

import httpx
import pytest

from crawl_tool.engine.agent import AgentConfig, run_agent
from crawl_tool.engine.crawler import fetch_page
from crawl_tool.engine.date_filter import detect_page_date, is_in_range
from crawl_tool.engine.prompt_parser import parse_crawl_prompt

requires_anthropic_key = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY is required for agent integration tests",
)
requires_webshare_proxy_list = pytest.mark.skipif(
    not (os.getenv("WEBSHARE_PROXY_LIST_URL") or os.getenv("WEBSHARE_PROXY_LIST_FILE")),
    reason=(
        "WEBSHARE_PROXY_LIST_URL or WEBSHARE_PROXY_LIST_FILE is required "
        "for proxy list integration tests"
    ),
)

# ---------------------------------------------------------------------------
# Site smoke tests — crawl completes, pages returned, no crashes
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_anthropic_key
async def test_parse_crawl_prompt_live_returns_structured_request():
    """One-shot natural-language prompt parsing returns usable crawl fields."""
    parsed = await parse_crawl_prompt(
        "Crawl https://cafef.vn for Vietnamese economy news from the last 7 days, max 2 pages"
    )

    assert parsed["seed_url"] == "https://cafef.vn"
    assert "econom" in parsed.get("goal", "").lower()
    assert parsed.get("max_pages") == 2
    assert "last 7 days" in parsed.get("date_filter", "").lower()


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


def _proxy_url_from_webshare_line(line: str) -> str:
    fields = line.strip().split(":")
    if "@" in line:
        return line if "://" in line else f"http://{line}"
    if len(fields) == 4:
        host, port, username, password = fields
        return f"http://{username}:{password}@{host}:{port}"
    if len(fields) == 2:
        host, port = fields
        return f"http://{host}:{port}"
    raise ValueError("unsupported Webshare proxy line format")


async def _fetch_public_ip(proxy_url: str) -> str:
    async with httpx.AsyncClient(proxy=proxy_url, timeout=20.0, trust_env=False) as client:
        response = await client.get("https://ipv4.webshare.io/")
        response.raise_for_status()
        return response.text.strip()


async def _load_webshare_proxy_lines() -> list[str]:
    list_file = os.getenv("WEBSHARE_PROXY_LIST_FILE")
    if list_file:
        return [
            line.strip()
            for line in Path(list_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    list_url = os.environ["WEBSHARE_PROXY_LIST_URL"]
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        response = await client.get(list_url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            pytest.fail(f"proxy list download failed with HTTP {exc.response.status_code}")
    return [line.strip() for line in response.text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Proxy integration — Webshare list has rotating exit IPs
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@requires_webshare_proxy_list
async def test_webshare_proxy_list_rotates_public_ip():
    """Downloaded Webshare proxy list exposes at least two distinct public IPs."""
    proxy_urls = [
        _proxy_url_from_webshare_line(line) for line in await _load_webshare_proxy_lines()
    ][:5]
    assert len(proxy_urls) >= 2, "proxy list must contain at least two entries"

    observed_ips = []
    failures = 0
    for proxy_url in proxy_urls:
        try:
            observed_ips.append(await _fetch_public_ip(proxy_url))
        except httpx.HTTPError:
            failures += 1

    assert len(observed_ips) >= 2, (
        f"need at least two successful proxy observations, got {len(observed_ips)} "
        f"successes and {failures} failures"
    )
    assert len(set(observed_ips)) >= 2, f"proxy list did not rotate IPs: {observed_ips}"


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
