"""Tests for src/date_filter.py — parse_date_filter, detect_page_date, is_in_range."""

from __future__ import annotations

from datetime import date

import pytest

from src.date_filter import detect_page_date, is_in_range, parse_date_filter
from src.models import PageResult

_TODAY = date(2026, 6, 4)


def _page(url: str = "https://cafef.vn", metadata: dict | None = None, headers: dict | None = None) -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=200,
        title="Article",
        markdown="content",
        metadata=metadata or {},
        headers=headers or {},
    )


@pytest.mark.parametrize(
    ("prompt", "expected_from", "expected_to"),
    [
        ("last 7 days", date(2026, 5, 28), date(2026, 6, 4)),
        ("last 2 weeks", date(2026, 5, 21), date(2026, 6, 4)),
        ("last 1 month", date(2026, 5, 5), date(2026, 6, 4)),
        ("last week", date(2026, 5, 28), date(2026, 6, 4)),
        ("last month", date(2026, 5, 5), date(2026, 6, 4)),
        ("last year", date(2025, 6, 4), date(2026, 6, 4)),
        ("this week", date(2026, 6, 1), date(2026, 6, 4)),
        ("this month", date(2026, 6, 1), date(2026, 6, 4)),
        ("this year", date(2026, 1, 1), date(2026, 6, 4)),
        ("today", date(2026, 6, 4), date(2026, 6, 4)),
        ("yesterday", date(2026, 6, 3), date(2026, 6, 3)),
        ("since 2026-06-01", date(2026, 6, 1), date(2026, 6, 4)),
        ("between 2026-05-01 and 2026-06-01", date(2026, 5, 1), date(2026, 6, 1)),
        ("2026-06-04", date(2026, 6, 4), date(2026, 6, 4)),
    ],
)
def test_parse_date_filter(prompt: str, expected_from: date, expected_to: date):
    from_date, to_date = parse_date_filter(prompt, today=_TODAY)
    assert from_date == expected_from
    assert to_date == expected_to


def test_parse_date_filter_raises_on_unrecognised_prompt():
    with pytest.raises(ValueError, match="cannot parse date filter"):
        parse_date_filter("next quarter", today=_TODAY)


def test_detect_page_date_from_article_published_time():
    page = _page(metadata={"article:published_time": "2026-06-03T09:16:00+07:00"})
    assert detect_page_date(page) == date(2026, 6, 3)


def test_detect_page_date_from_og_updated_time():
    page = _page(metadata={"og:updated_time": "2026-06-02T00:00:00Z"})
    assert detect_page_date(page) == date(2026, 6, 2)


def test_detect_page_date_from_date_published():
    page = _page(metadata={"datePublished": "2026-05-30T12:00:00Z"})
    assert detect_page_date(page) == date(2026, 5, 30)


def test_detect_page_date_from_last_modified_header():
    page = _page(headers={"Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT"})
    assert detect_page_date(page) == date(2026, 6, 3)


def test_detect_page_date_from_cafef_url_pattern():
    page = _page(url="https://cafef.vn/gia-vang-188260603074758376.chn")
    page.final_url = page.url
    assert detect_page_date(page) == date(2026, 6, 3)


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
