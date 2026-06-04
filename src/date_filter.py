"""NL date filter parsing and page date detection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from src.models import PageResult

logger = logging.getLogger(__name__)


@dataclass
class DateRange:
    """Resolved date range from a natural-language filter."""

    start: date | None
    end: date | None

    def __str__(self) -> str:
        return f"[{self.start or '...'} → {self.end or '...'}]"


def parse_date_filter(prompt: str, today: date | None = None) -> tuple[date, date]:
    """Parse a natural-language date filter into an inclusive (from_date, to_date) range.

    Supports:
        - "last N days / weeks / months"
        - "last week / month / year"
        - "this week / month / year"
        - "today", "yesterday"
        - "since YYYY-MM-DD"
        - "between YYYY-MM-DD and YYYY-MM-DD"
        - "YYYY-MM-DD" (exact date)

    Args:
        prompt: Natural-language date filter string.
        today: Override for the current date (used in tests).

    Returns:
        Inclusive (from_date, to_date) tuple.

    Raises:
        ValueError: If the filter text cannot be parsed.
    """
    if today is None:
        today = date.today()
    text = prompt.strip().lower()

    # "last N days/weeks/months"
    m = re.match(r"last\s+(\d+)\s+(day|week|month)s?$", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"day": timedelta(days=n), "week": timedelta(weeks=n), "month": timedelta(days=n * 30)}[unit]
        return (today - delta, today)

    # "last week / month / year"
    m = re.match(r"last\s+(week|month|year)$", text)
    if m:
        delta = {"week": timedelta(weeks=1), "month": timedelta(days=30), "year": timedelta(days=365)}[m.group(1)]
        return (today - delta, today)

    # "this week / month / year"
    m = re.match(r"this\s+(week|month|year)$", text)
    if m:
        unit = m.group(1)
        if unit == "week":
            start = today - timedelta(days=today.weekday())
        elif unit == "month":
            start = today.replace(day=1)
        else:
            start = today.replace(month=1, day=1)
        return (start, today)

    if text == "today":
        return (today, today)

    if text == "yesterday":
        yesterday = today - timedelta(days=1)
        return (yesterday, yesterday)

    # "since YYYY-MM-DD" — open upper bound treated as today
    m = re.match(r"since\s+(\d{4}-\d{2}-\d{2})$", text)
    if m:
        return (date.fromisoformat(m.group(1)), today)

    # "between YYYY-MM-DD and YYYY-MM-DD"
    m = re.match(r"between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})$", text)
    if m:
        return (date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2)))

    # "YYYY-MM-DD"
    m = re.match(r"(\d{4}-\d{2}-\d{2})$", text)
    if m:
        d = date.fromisoformat(m.group(1))
        return (d, d)

    raise ValueError(f"cannot parse date filter: {prompt!r}")


def detect_page_date(page: PageResult) -> date | None:
    """Extract the publish date from a fetched page.

    Checks in priority order:
        1. ``article:published_time`` / ``og:updated_time`` meta tags
        2. JSON-LD ``datePublished`` / ``dateModified``
        3. HTTP ``Last-Modified`` response header
        4. URL-embedded date (Vietnamese news pattern: ``188YYMMDD…``)

    Args:
        page: Fetched page whose metadata, headers, and URL are inspected.

    Returns:
        Detected publish date, or None if no date can be determined.
    """
    metadata = page.metadata or {}

    for key in ("article:published_time", "og:updated_time", "datePublished", "dateModified"):
        raw = metadata.get(key)
        if raw:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                pass

    # HTTP Last-Modified header (lowest priority among explicit signals)
    headers = page.headers or {}
    last_modified = headers.get("last-modified") or headers.get("Last-Modified")
    if last_modified:
        try:
            return parsedate_to_datetime(last_modified).date()
        except Exception:  # noqa: BLE001
            pass

    # Vietnamese news URL pattern: /slug-1[88]YYMMDDHHMMSSID.chn
    m = re.search(r"1\d{2}(\d{2})(\d{2})(\d{2})\d+\.chn", page.final_url)
    if m:
        try:
            return date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def is_in_range(
    page_date: date | None,
    from_date: date,
    to_date: date,
    include_undated: bool = False,
) -> bool:
    """Check whether a page falls within the date range.

    Args:
        page_date: Detected publish date of the page, or None.
        from_date: Inclusive lower bound of the accepted date range.
        to_date: Inclusive upper bound of the accepted date range.
        include_undated: Whether to include pages with no detectable date.

    Returns:
        True if the page should be included in results.
    """
    if page_date is None:
        return include_undated
    return from_date <= page_date <= to_date
