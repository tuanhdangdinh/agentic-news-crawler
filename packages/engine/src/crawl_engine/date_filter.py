"""NL date filter parsing and page date detection."""

from __future__ import annotations

import json
import re
from calendar import monthrange
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import dateparser

from crawl_engine.models import PageResult

# Relative-phrase patterns matched anywhere in the filter text (not anchored to
# the full string) so compound filters like "articles from last week about
# banks" resolve via the embedded "last week" phrase. Safe to search for
# unanchored because none of these contain a free-form date token — unlike
# "since <date>" / "between <date> and <date>", which keep requiring a
# standalone phrase below.
_LAST_N_RE = re.compile(r"\blast\s+(\d+)\s+(day|week|month)s?\b")
_LAST_UNIT_RE = re.compile(r"\blast\s+(week|month|year)\b")
_THIS_UNIT_RE = re.compile(r"\bthis\s+(week|month|year)\b")
_TODAY_RE = re.compile(r"\btoday\b")
_YESTERDAY_RE = re.compile(r"\byesterday\b")


def _rolling_month_start(today: date, months: int) -> date:
    month_index = today.year * 12 + today.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(today.day, monthrange(year, month)[1])
    return date(year, month, day) + timedelta(days=1)


def _match_relative_phrase(text: str, today: date) -> tuple[date, date] | None:
    """Find a relative date phrase anywhere in ``text`` and resolve its range.

    Returns ``None`` if no relative phrase is present, so the caller can fall
    back to the standalone absolute-date branches (``since``, ``between``, bare
    date) which still require the filter to be just that phrase.
    """
    m = _LAST_N_RE.search(text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if n <= 0:
            raise ValueError("date range count must be positive")
        if unit == "month":
            return (_rolling_month_start(today, n), today)
        days = {"day": n, "week": n * 7}[unit]
        return (today - timedelta(days=days - 1), today)

    m = _LAST_UNIT_RE.search(text)
    if m:
        unit = m.group(1)
        if unit in {"month", "year"}:
            return (_rolling_month_start(today, 1 if unit == "month" else 12), today)
        days = 7
        return (today - timedelta(days=days - 1), today)

    m = _THIS_UNIT_RE.search(text)
    if m:
        unit = m.group(1)
        if unit == "week":
            start = today - timedelta(days=today.weekday())
        elif unit == "month":
            start = today.replace(day=1)
        else:
            start = today.replace(month=1, day=1)
        return (start, today)

    if _TODAY_RE.search(text):
        return (today, today)

    if _YESTERDAY_RE.search(text):
        yesterday = today - timedelta(days=1)
        return (yesterday, yesterday)

    return None


def _parse_one_date(token: str, today: date) -> date:
    """Parse a single date token, ISO first then natural language.

    ISO ``YYYY-MM-DD`` is tried directly so the common case stays deterministic
    and fast. Anything else (``June 1st``, ``1 June 2026``, ``1 tháng 6``) falls
    back to ``dateparser`` with ``today`` as the relative base.

    Raises:
        ValueError: If the token cannot be resolved to a date.
    """
    token = token.strip()
    try:
        return date.fromisoformat(token)
    except ValueError:
        pass

    parsed = dateparser.parse(
        token,
        settings={
            "RELATIVE_BASE": datetime(today.year, today.month, today.day),
            "PREFER_DATES_FROM": "past",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if parsed is None:
        raise ValueError(f"cannot parse date: {token!r}")
    return parsed.date()


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

    # Relative phrases ("last 7 days", "this month", "today", ...) may be
    # embedded in a larger sentence — search for them anywhere in the text.
    relative = _match_relative_phrase(text, today)
    if relative is not None:
        return relative

    # "since <date>" — may be embedded ("articles published since June 1st about banks")
    m = re.search(r"\bsince\s+(.+)", text)
    if m:
        rest = m.group(1).split()
        for n in range(len(rest), 0, -1):
            try:
                return (_parse_one_date(" ".join(rest[:n]), today), today)
            except ValueError:
                continue
        raise ValueError(f"cannot parse date filter: {prompt!r}")

    # "between <date> and <date>" — may be embedded
    m = re.search(r"\bbetween\s+(.+?)\s+and\s+(.+)", text)
    if m:
        left = m.group(1).strip()
        right_words = m.group(2).split()
        try:
            from_date = _parse_one_date(left, today)
        except ValueError:
            raise ValueError(f"cannot parse date filter: {prompt!r}") from None
        for n in range(len(right_words), 0, -1):
            try:
                to_date = _parse_one_date(" ".join(right_words[:n]), today)
            except ValueError:
                continue
            if from_date > to_date:
                raise ValueError("start date must not be after end date")
            return (from_date, to_date)
        raise ValueError(f"cannot parse date filter: {prompt!r}")

    # Bare single date — "2026-06-04", "June 1st", "1 thang 6"
    try:
        d = _parse_one_date(text, today)
    except ValueError:
        raise ValueError(f"cannot parse date filter: {prompt!r}") from None
    return (d, d)


_JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _iter_json_ld_nodes(data: object) -> Iterator[dict]:
    """Walk a parsed JSON-LD document, yielding every dict node including ``@graph`` members."""
    if isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                yield from _iter_json_ld_nodes(node)
    elif isinstance(data, list):
        for node in data:
            yield from _iter_json_ld_nodes(node)


def _extract_json_ld_date(html: str | None) -> date | None:
    """Parse ``datePublished``/``dateModified`` directly out of JSON-LD ``<script>`` blocks.

    Crawl4AI only promotes JSON-LD fields into ``page.metadata`` when its own
    heuristics recognise them; pages where it doesn't still carry the raw
    ``<script type="application/ld+json">`` blocks in ``page.html``, so this
    scans those directly as a fallback before giving up on explicit signals.
    """
    if not html:
        return None

    for block in _JSON_LD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue

        for node in _iter_json_ld_nodes(data):
            for key in ("datePublished", "dateModified"):
                raw = node.get(key)
                if raw:
                    try:
                        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
                    except (ValueError, AttributeError):
                        continue

    return None


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

    json_ld_date = _extract_json_ld_date(page.html)
    if json_ld_date is not None:
        return json_ld_date

    # HTTP Last-Modified header (lowest priority among explicit signals)
    headers = page.headers or {}
    last_modified = headers.get("last-modified") or headers.get("Last-Modified")
    if last_modified:
        try:
            return parsedate_to_datetime(last_modified).date()
        except Exception:  # noqa: BLE001
            pass

    return detect_url_date(page.final_url)


# Plausible date window for Vietnamese online news — sites launched mid-2000s;
# allow up to 2 years in the future for scheduled or pre-published articles.
_NEWS_DATE_MIN = date(1995, 1, 1)
_NEWS_DATE_MAX_OFFSET_DAYS = 730


def _resolve_2digit_year(yy: int, mm: int, dd: int) -> date | None:
    """Resolve a 2-digit year to a full date within the plausible news window.

    Tries the 2000s century first, then the 1900s.  Returns ``None`` when
    neither candidate falls inside ``[1995-01-01, today + 2 years]``.
    """
    cutoff = date.today() + timedelta(days=_NEWS_DATE_MAX_OFFSET_DAYS)
    for century in (2000, 1900):
        try:
            candidate = date(century + yy, mm, dd)
        except ValueError:
            continue
        if _NEWS_DATE_MIN <= candidate <= cutoff:
            return candidate
    return None


def detect_url_date(url: str) -> date | None:
    """Extract a publish date embedded in a Vietnamese news article URL.

    Handles two common encodings:
        - CafeF: ``/slug-1NNyyMMddHHmmssID.chn`` (2-digit year after a 1NN prefix)
        - TuoiTre / generic: ``/slug-yyyyMMddHHmmssID.htm`` (4-digit year)

    Args:
        url: Article URL to inspect.

    Returns:
        Detected date, or None when the URL carries no recognisable date.
    """
    # CafeF: 1NN prefix then 2-digit year, month, day
    m = re.search(r"-1\d{2}(\d{2})(\d{2})(\d{2})\d+\.chn$", url)
    if m:
        resolved = _resolve_2digit_year(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if resolved is not None:
            return resolved

    # TuoiTre / generic: 4-digit year, month, day before a long id and .htm(l)
    m = re.search(r"-(\d{4})(\d{2})(\d{2})\d{6,}\.html?$", url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
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
