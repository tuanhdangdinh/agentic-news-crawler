"""Tests for src/agent.py helper behaviours."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crawl_tool.engine.agent import (
    AgentConfig,
    _allowed,
    _article_candidate_links,
    _canonical,
    _is_article_page,
    _parse_min_articles,
    _same_domain,
)
from crawl_tool.engine.models import PageResult


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


def test_is_article_page_detects_generic_article_url():
    page = _page("https://vietnamnews.vn/economy/1782728/global-rubber-prices-surge.html")
    assert _is_article_page(page)


def test_is_article_page_rejects_homepage_and_category():
    assert not _is_article_page(_page("https://cafef.vn"))
    assert not _is_article_page(_page("https://cafef.vn/tai-chinh-ngan-hang.chn"))
    assert not _is_article_page(_page("https://vietnamnews.vn/economy"))


def test_article_candidate_links_returns_known_article_pattern_matches():
    links = [
        "https://vneconomy.vn/tai-chinh.htm",
        "https://vneconomy.vn/ngan-hang-nha-nuoc-hut-rong-gan-32000-ty-dong.htm",
        "https://vietnamnews.vn/economy/1782728/global-rubber-prices-surge.html",
        "https://example.com/article.html",
    ]
    assert _article_candidate_links(links) == [
        "https://vneconomy.vn/ngan-hang-nha-nuoc-hut-rong-gan-32000-ty-dong.htm",
        "https://vietnamnews.vn/economy/1782728/global-rubber-prices-surge.html",
    ]


def test_canonical_strips_fragment():
    assert _canonical("https://cafef.vn/article.chn#section") == "https://cafef.vn/article.chn"


def test_canonical_preserves_url_without_fragment():
    assert _canonical("https://cafef.vn/article.chn") == "https://cafef.vn/article.chn"


def test_canonical_normalizes_query_param_order():
    assert (
        _canonical("https://cafef.vn/article.chn?b=2&a=1") == "https://cafef.vn/article.chn?a=1&b=2"
    )


def test_canonical_keeps_blank_query_values():
    assert _canonical("https://cafef.vn/article.chn?a=") == "https://cafef.vn/article.chn?a="


def test_agent_config_rejects_depth_above_ceiling():
    with pytest.raises(ValidationError):
        AgentConfig(max_depth=6)


def test_agent_config_accepts_depth_at_ceiling():
    assert AgentConfig(max_depth=5).max_depth == 5


def test_same_domain_accepts_same_domain():
    assert _same_domain("https://cafef.vn", "https://cafef.vn/article.chn")


def test_same_domain_rejects_different_domain():
    assert not _same_domain("https://cafef.vn", "https://vneconomy.vn/article.chn")


def test_allowed_blocks_off_domain_when_same_domain_true():
    assert not _allowed("https://vneconomy.vn", "https://cafef.vn", AgentConfig(same_domain=True))


def test_allowed_permits_off_domain_when_same_domain_false():
    assert _allowed("https://vneconomy.vn", "https://cafef.vn", AgentConfig(same_domain=False))


def test_allowed_blocks_excluded_pattern():
    config = AgentConfig(exclude_patterns=["*/ads/*"])
    assert not _allowed("https://cafef.vn/ads/banner.chn", "https://cafef.vn", config)


def test_allowed_permits_url_not_matching_exclude_pattern():
    config = AgentConfig(exclude_patterns=["*/ads/*"])
    assert _allowed("https://cafef.vn/article.chn", "https://cafef.vn", config)


def test_allowed_requires_include_pattern_when_set():
    config = AgentConfig(same_domain=False, include_patterns=["*/economy/*"])
    assert not _allowed("https://cafef.vn/sports/news.chn", "https://cafef.vn", config)
    assert _allowed("https://cafef.vn/economy/news.chn", "https://cafef.vn", config)
