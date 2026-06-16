"""Tests for src/date_filter.py — parse_date_filter, detect_page_date, is_in_range."""

from __future__ import annotations

from datetime import date

import pytest
from crawl_tool.engine.date_filter import detect_page_date, is_in_range, parse_date_filter
from crawl_tool.engine.models import PageResult

_TODAY = date(2026, 6, 4)


def _page(
    url: str = "https://cafef.vn",
    metadata: dict | None = None,
    headers: dict | None = None,
    html: str | None = None,
) -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=200,
        title="Article",
        markdown="content",
        metadata=metadata or {},
        headers=headers or {},
        html=html,
    )


@pytest.mark.parametrize(
    ("prompt", "expected_from", "expected_to"),
    [
        ("last 7 days", date(2026, 5, 29), date(2026, 6, 4)),
        ("last 2 weeks", date(2026, 5, 22), date(2026, 6, 4)),
        ("last 1 month", date(2026, 5, 5), date(2026, 6, 4)),
        ("last week", date(2026, 5, 29), date(2026, 6, 4)),
        ("last month", date(2026, 5, 5), date(2026, 6, 4)),
        ("last year", date(2025, 6, 5), date(2026, 6, 4)),
        ("this week", date(2026, 6, 1), date(2026, 6, 4)),
        ("this month", date(2026, 6, 1), date(2026, 6, 4)),
        ("this year", date(2026, 1, 1), date(2026, 6, 4)),
        ("today", date(2026, 6, 4), date(2026, 6, 4)),
        ("yesterday", date(2026, 6, 3), date(2026, 6, 3)),
        ("since 2026-06-01", date(2026, 6, 1), date(2026, 6, 4)),
        ("between 2026-05-01 and 2026-06-01", date(2026, 5, 1), date(2026, 6, 1)),
        ("2026-06-04", date(2026, 6, 4), date(2026, 6, 4)),
        # Natural-language dates via dateparser fallback
        ("since June 1st", date(2026, 6, 1), date(2026, 6, 4)),
        ("since June 1 2026", date(2026, 6, 1), date(2026, 6, 4)),
        ("between May 1 2026 and June 1 2026", date(2026, 5, 1), date(2026, 6, 1)),
        ("June 1 2026", date(2026, 6, 1), date(2026, 6, 1)),
        ("1 June 2026", date(2026, 6, 1), date(2026, 6, 1)),
    ],
)
def test_parse_date_filter(prompt: str, expected_from: date, expected_to: date):
    from_date, to_date = parse_date_filter(prompt, today=_TODAY)
    assert from_date == expected_from
    assert to_date == expected_to


@pytest.mark.parametrize("prompt", ["next quarter", "sometime recently", "gibberish xyz", ""])
def test_parse_date_filter_raises_on_unrecognised_prompt(prompt: str):
    with pytest.raises(ValueError, match="cannot parse date filter"):
        parse_date_filter(prompt, today=_TODAY)


def test_parse_date_filter_rejects_non_positive_count():
    with pytest.raises(ValueError, match="positive"):
        parse_date_filter("last 0 days", today=_TODAY)


def test_parse_date_filter_uses_calendar_month_boundaries():
    assert parse_date_filter("last month", today=date(2026, 3, 31)) == (
        date(2026, 3, 1),
        date(2026, 3, 31),
    )


def test_parse_date_filter_rejects_reversed_between_range():
    with pytest.raises(ValueError, match="start date must not be after end date"):
        parse_date_filter("between 2026-06-04 and 2026-06-01", today=_TODAY)


@pytest.mark.parametrize(
    ("prompt", "expected_from", "expected_to"),
    [
        ("articles from last week about banks", date(2026, 5, 29), date(2026, 6, 4)),
        ("give me last 7 days of stock news", date(2026, 5, 29), date(2026, 6, 4)),
        ("show me posts from this month please", date(2026, 6, 1), date(2026, 6, 4)),
        ("anything posted today would be great", date(2026, 6, 4), date(2026, 6, 4)),
        ("yesterday's banking headlines", date(2026, 6, 3), date(2026, 6, 3)),
    ],
)
def test_parse_date_filter_finds_relative_phrase_in_compound_text(
    prompt: str, expected_from: date, expected_to: date
):
    from_date, to_date = parse_date_filter(prompt, today=_TODAY)
    assert from_date == expected_from
    assert to_date == expected_to


@pytest.mark.parametrize(
    ("prompt", "expected_from", "expected_to"),
    [
        # "since" embedded in a sentence
        ("articles published since 2026-06-01 about banks", date(2026, 6, 1), date(2026, 6, 4)),
        ("news since June 1 2026 on the stock market", date(2026, 6, 1), date(2026, 6, 4)),
        # "between … and …" embedded in a sentence
        (
            "show articles between 2026-05-01 and 2026-06-01 on economy",
            date(2026, 5, 1),
            date(2026, 6, 1),
        ),
        (
            "content between May 1 2026 and June 1 2026 about banks",
            date(2026, 5, 1),
            date(2026, 6, 1),
        ),
    ],
)
def test_parse_date_filter_finds_absolute_phrase_in_compound_text(
    prompt: str, expected_from: date, expected_to: date
):
    from_date, to_date = parse_date_filter(prompt, today=_TODAY)
    assert from_date == expected_from
    assert to_date == expected_to


def test_detect_page_date_from_article_published_time():
    page = _page(metadata={"article:published_time": "2026-06-03T09:16:00+07:00"})
    assert detect_page_date(page) == date(2026, 6, 3)


def test_detect_page_date_from_og_updated_time():
    page = _page(metadata={"og:updated_time": "2026-06-02T00:00:00Z"})
    assert detect_page_date(page) == date(2026, 6, 2)


def test_detect_page_date_from_date_published():
    page = _page(metadata={"datePublished": "2026-05-30T12:00:00Z"})
    assert detect_page_date(page) == date(2026, 5, 30)


def test_detect_page_date_from_json_ld_in_html():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "NewsArticle", "datePublished": "2026-06-02T08:00:00+07:00"}
    </script>
    </head></html>
    """
    page = _page(html=html)
    assert detect_page_date(page) == date(2026, 6, 2)


def test_detect_page_date_from_json_ld_graph_array():
    html = """
    <script type="application/ld+json">
    {"@graph": [{"@type": "WebPage"}, {"@type": "Article", "dateModified": "2026-05-29T12:00:00Z"}]}
    </script>
    """
    page = _page(html=html)
    assert detect_page_date(page) == date(2026, 5, 29)


def test_detect_page_date_ignores_malformed_json_ld():
    html = '<script type="application/ld+json">{not valid json</script>'
    page = _page(url="https://cafef.vn/category", html=html)
    assert detect_page_date(page) is None


def test_detect_page_date_meta_takes_priority_over_json_ld():
    html = '<script type="application/ld+json">{"datePublished": "2026-05-20T00:00:00Z"}</script>'
    page = _page(metadata={"article:published_time": "2026-06-01T00:00:00Z"}, html=html)
    assert detect_page_date(page) == date(2026, 6, 1)


def test_detect_page_date_json_ld_takes_priority_over_header():
    html = '<script type="application/ld+json">{"datePublished": "2026-05-25T00:00:00Z"}</script>'
    page = _page(headers={"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"}, html=html)
    assert detect_page_date(page) == date(2026, 5, 25)


def test_detect_page_date_from_last_modified_header():
    page = _page(headers={"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"})
    assert detect_page_date(page) == date(2026, 6, 3)


def test_detect_page_date_from_cafef_url_pattern():
    page = _page(url="https://cafef.vn/gia-vang-188260603074758376.chn")
    page.final_url = page.url
    assert detect_page_date(page) == date(2026, 6, 3)


def test_detect_page_date_from_tuoitre_url_pattern():
    page = _page(url="https://tuoitre.vn/lg-innotek-hai-phong-20260604161445695.htm")
    page.final_url = page.url
    assert detect_page_date(page) == date(2026, 6, 4)


def test_detect_page_date_returns_none_when_no_signal():
    page = _page(url="https://cafef.vn/category")
    assert detect_page_date(page) is None


def test_detect_page_date_meta_takes_priority_over_header():
    page = _page(
        metadata={"article:published_time": "2026-06-01T00:00:00Z"},
        headers={"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"},
    )
    assert detect_page_date(page) == date(2026, 6, 1)


def test_is_in_range_includes_page_within_range():
    assert is_in_range(date(2026, 6, 2), date(2026, 6, 1), date(2026, 6, 4))


def test_is_in_range_includes_page_on_boundary():
    assert is_in_range(date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 4))
    assert is_in_range(date(2026, 6, 4), date(2026, 6, 1), date(2026, 6, 4))


def test_is_in_range_excludes_page_outside_range():
    assert not is_in_range(date(2026, 5, 31), date(2026, 6, 1), date(2026, 6, 4))
    assert not is_in_range(date(2026, 6, 5), date(2026, 6, 1), date(2026, 6, 4))


def test_is_in_range_excludes_undated_page_by_default():
    assert not is_in_range(None, date(2026, 6, 1), date(2026, 6, 4))


def test_is_in_range_includes_undated_page_when_flag_set():
    assert is_in_range(None, date(2026, 6, 1), date(2026, 6, 4), include_undated=True)


# ---------------------------------------------------------------------------
# detect_url_date — 2-digit year century resolution
# ---------------------------------------------------------------------------


def test_detect_url_date_cafef_current_year_resolves_to_2000s():
    from crawl_tool.engine.date_filter import detect_url_date

    # YY=26 → 2026, which is within the plausible window
    assert detect_url_date("https://cafef.vn/bai-viet-188260603074758376.chn") == date(2026, 6, 3)


def test_detect_url_date_cafef_far_future_yy_falls_back_to_1900s():
    from datetime import date as _date

    from crawl_tool.engine.date_filter import detect_url_date

    # YY that puts 2000+YY well past today+2years must fall back to 1900s
    # Use YY=98 → 2098 (implausible) → falls back to 1998
    result = detect_url_date("https://cafef.vn/bai-viet-188980603074758376.chn")
    assert result == _date(1998, 6, 3)


def test_detect_url_date_cafef_implausible_both_centuries_returns_none():
    from crawl_tool.engine.date_filter import detect_url_date

    # YY=50 → 2050 (too far future) → 1950 (before 1995 min) → None
    result = detect_url_date("https://cafef.vn/bai-viet-188500603074758376.chn")
    assert result is None


def test_detect_url_date_cafef_invalid_month_returns_none():
    from crawl_tool.engine.date_filter import detect_url_date

    # month=13 is always invalid regardless of century
    result = detect_url_date("https://cafef.vn/bai-viet-188261303074758376.chn")
    assert result is None
