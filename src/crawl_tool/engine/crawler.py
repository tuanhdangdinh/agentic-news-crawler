"""Thin async wrapper around Crawl4AI."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import structlog
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.antibot_detector import is_blocked as _antibot_is_blocked
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from crawl_tool.engine.models import PageResult
from crawl_tool.engine.proxy import ProxyRotator

logger = structlog.get_logger(__name__)

# Identifies the tool and a contact address to crawled sites (compliance requirement).
USER_AGENT = "crawl-tool/0.1 (+mailto:tuanhdangdinh@gmail.com)"

_BROWSER_CFG = BrowserConfig(browser_type="chromium", headless=True, user_agent=USER_AGENT)

_RUN_CFG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    check_robots_txt=True,
    excluded_tags=["script", "style", "noscript", "form"],
    remove_forms=True,
    remove_overlay_elements=True,
    markdown_generator=DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.6),
        options={"ignore_links": True},
    ),
)

# Maps netloc (without www.) → (article URL pattern, CSS selector for body).
# When a URL matches the pattern, the selector scopes the fetch to the article
# body only, cutting 60–82% of tokens on article pages.
_ARTICLE_SELECTORS: dict[str, tuple[str, str]] = {
    "cafef.vn": (r"/[^/]+-\d{9,}\.chn$", ".detail-content"),
    "tuoitre.vn": (r"/[^/]+-\d{12,}\.htm$", ".detail-content"),
    "vneconomy.vn": (r"/[^/]{30,}\.htm$", ".block-detail-page"),
}

_ARTICLE_TARGETS: dict[str, tuple[str, list[str]]] = {
    "nhandan.vn": (
        r"/[^/]+-post\d+\.html$",
        [".main-col.content-col"],
    ),
    "baodautu.vn": (
        r"/[^/]+-d\d+\.html$",
        [".col630.ml-auto.mb40"],
    ),
    "vietnamplus.vn": (
        r"/[^/]+-post\d+\.vnp$",
        [
            ".article__title",
            ".article__sapo",
            ".article__meta",
            ".article__body.zce-content-body.cms-body",
        ],
    ),
}

_GENERIC_ARTICLE_TARGETS = [
    ".detail .headline",
    ".detail__meta",
    ".datetime",
    ".title-detail",
    ".author-share-top",
    ".author-detail",
    ".byline",
    ".article-author",
    ".author-name",
    ".cms-author",
    ".author",
    "[itemprop='author']",
    ".sapo_detail",
    ".sapo",
    ".article__title",
    ".article__sapo",
    ".article__meta",
    "[itemprop='headline']",
    "[itemprop='datePublished']",
    "[itemprop='description']",
    "[itemprop='articleBody']",
    "#abody",
    ".article__content",
    ".article-content",
    ".article-body",
    ".articleBody",
    ".article-text",
    ".article-body-content",
    ".story-content",
    ".story-body",
    ".post-content",
    ".entry-content",
    ".detail-content",
    ".content-detail",
    ".news-detail",
    ".article-detail",
    ".body-content",
]

_GENERIC_ARTICLE_PATTERNS = [
    re.compile(r"/\d{5,}/[^/]+(?:-[^/]+){2,}\.(?:html?|shtml)$"),
    re.compile(r"/[^/]+-\d{8,}\.(?:html?|shtml)$"),
    re.compile(r"/[^/]+-post\d+\.html$"),
    re.compile(r"/[^/]+-post\d+\.vnp$"),
    re.compile(r"/[^/]+(?:-[^/]+){5,}\.(?:html?|shtml)$"),
]

_BYLINE_SELECTORS = [
    ".author-detail",
    ".__MB_AUTHOR",
    ".byline",
    ".article-author",
    ".news-author",
    ".detail-author",
    ".author-name",
    ".cms-author",
    ".author",
    "[itemprop='author']",
    "[rel='author']",
]

_MIN_SCOPED_MARKDOWN_CHARS = 200
_DEFAULT_FETCH_ATTEMPTS = 4


def article_selector_for_url(url: str) -> str | None:
    """Return the article-body CSS selector for a known site URL, or None.

    Known selectors are preferred over generic detection because they are cleaner
    and less likely to include sidebars or related links.

    Args:
        url: URL to match against known article patterns.

    Returns:
        Matching article-body selector, or None for an unknown URL.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.")
    entry = _ARTICLE_SELECTORS.get(domain)
    if entry is None:
        return None
    pattern, selector = entry
    return selector if re.search(pattern, parsed.path) else None


def looks_like_article_url(url: str) -> bool:
    """Check whether a URL matches known or generic article patterns.

    Args:
        url: URL to classify.

    Returns:
        True when the URL appears to identify an article.
    """
    if article_selector_for_url(url) is not None:
        return True

    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.")
    entry = _ARTICLE_TARGETS.get(domain)
    if entry is not None:
        pattern, _targets = entry
        if re.search(pattern, parsed.path):
            return True

    path = parsed.path.rstrip("/")
    return any(pattern.search(path) for pattern in _GENERIC_ARTICLE_PATTERNS)


def article_target_elements_for_url(url: str) -> list[str]:
    """Return target elements for an article URL.

    Args:
        url: URL used to select known or generic article targets.

    Returns:
        Preferred target selectors, or an empty list for a non-article URL.
    """
    selector = article_selector_for_url(url)
    if selector is not None:
        return [selector]

    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.")
    entry = _ARTICLE_TARGETS.get(domain)
    if entry is not None:
        pattern, targets = entry
        if re.search(pattern, parsed.path):
            return list(targets)

    return list(_GENERIC_ARTICLE_TARGETS) if looks_like_article_url(url) else []


def _make_cfg(
    css_selector: str | None = None,
    target_elements: list[str] | None = None,
) -> CrawlerRunConfig:
    """Build a run config.

    css_selector hard-scopes the whole extraction (HTML, metadata, links, markdown)
    to a region. target_elements scopes only markdown generation, leaving head
    metadata and full-page links intact — used for article-body auto-detection so
    title/date metadata and navigation links survive.
    """
    if not css_selector and not target_elements:
        return _RUN_CFG
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        check_robots_txt=True,
        excluded_tags=["script", "style", "noscript", "form"],
        remove_forms=True,
        remove_overlay_elements=True,
        css_selector=css_selector,
        target_elements=target_elements,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.6),
            options={"ignore_links": True},
        ),
    )


def _extract_links(links_dict: dict) -> tuple[list[str], list[str]]:
    """Pull href strings from Crawl4AI's links dict."""
    internal = [lnk.get("href", "") for lnk in links_dict.get("internal", []) if lnk.get("href")]
    external = [lnk.get("href", "") for lnk in links_dict.get("external", []) if lnk.get("href")]
    return internal, external


def _clean_byline(text: str) -> str | None:
    """Normalize an explicit byline string."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(by|author)\s*[:\-]?\s+", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*[-–|]\s*[\w.+-]+@[\w.-]+\.\w+\s*$", "", text).strip()
    text = re.sub(r"\s*[-–|]\s*\d{1,2}[/:]\d{1,2}.*$", "", text).strip()
    if not text:
        return None
    lowered = text.lower()
    if any(token in lowered for token in ["advertisement", "subscribe", "comment"]):
        return None
    if len(text.split()) > 6:
        return None
    return text


def _has_usable_scoped_markdown(markdown: str) -> bool:
    """Return True when scoped article markdown is long enough to trust."""
    return len(markdown.strip()) >= _MIN_SCOPED_MARKDOWN_CHARS


def _extract_byline_author(html: str | None) -> str | None:
    """Extract an explicit article byline from full page HTML when present."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    for selector in _BYLINE_SELECTORS:
        for element in soup.select(selector):
            candidate = _clean_byline(element.get("content") or element.get_text(" ", strip=True))
            if candidate:
                return candidate
    return None


def _retry_after(result) -> float:
    """Extract Retry-After seconds from a response."""
    resp_hdrs = getattr(result, "response_headers", {}) or {}
    raw = resp_hdrs.get("retry-after") or resp_hdrs.get("Retry-After") or "60"
    try:
        return max(float(raw), 0.0)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max((retry_at - datetime.now(UTC)).total_seconds(), 0.0)
        except (TypeError, ValueError, OverflowError):
            return 60.0


# Substrings in Crawl4AI's antibot_detector reason text that indicate a named
# anti-bot vendor or challenge page, as opposed to a plain status-code block.
_VENDOR_BLOCK_KEYWORDS = (
    "cloudflare",
    "akamai",
    "perimeterx",
    "datadome",
    "imperva",
    "incapsula",
    "sucuri",
    "kasada",
    "captcha",
    "challenge",
    "network security",
)


def _is_blocked(result) -> bool:
    """Return True for HTTP 403/429, or a named anti-bot vendor/challenge
    signature detected by Crawl4AI's antibot_detector at any other status.

    5xx is deliberately excluded — it is handled as a transient error with
    same-proxy retry, never as a rotation-worthy block. Generic heuristics
    (near-empty body, missing structural markers) are deliberately not
    consulted outside 403/429 — they're calibrated for raw full-page HTML and
    would flag ordinary short or stubbed 200 responses; this codebase already
    handles unusably short scoped content via a separate full-page retry.
    """
    status = result.status_code or 0
    if status in (403, 429):
        return True
    if status >= 500:
        return False
    _, native_reason = _antibot_is_blocked(status, result.html or "", result.error_message)
    return any(keyword in native_reason.lower() for keyword in _VENDOR_BLOCK_KEYWORDS)


def _block_reason(result) -> str:
    """Classify a block for logging and rotation tracking. "" when not blocked."""
    status = result.status_code or 0
    if not _is_blocked(result):
        return ""
    _, native_reason = _antibot_is_blocked(status, result.html or "", result.error_message)
    if any(keyword in native_reason.lower() for keyword in _VENDOR_BLOCK_KEYWORDS):
        return "captcha"
    return f"http_{status}" if status else "blocked"


def _build_success_result(url: str, result, fetch_time: float) -> PageResult:
    """Build a PageResult from a successful CrawlResult."""
    md = result.markdown
    markdown = (md.fit_markdown or md.raw_markdown) if md else ""
    raw_markdown = md.raw_markdown if md else None
    internal, external = _extract_links(result.links or {})
    metadata = result.metadata or {}
    byline_author = None
    if looks_like_article_url(result.url or url):
        byline_author = _extract_byline_author(result.html)
    if byline_author:
        metadata["byline_author"] = byline_author
    title = metadata.get("title") or metadata.get("og:title")
    resp_hdrs = getattr(result, "response_headers", {}) or {}
    logger.info(
        "fetch ok",
        url=url,
        status=result.status_code,
        chars=len(markdown),
        links=len(internal),
        time=fetch_time,
    )
    return PageResult(
        url=url,
        final_url=result.url,
        status_code=result.status_code,
        title=title,
        markdown=markdown,
        raw_markdown=raw_markdown,
        html=result.html,
        links_internal=internal,
        links_external=external,
        metadata=metadata,
        headers=resp_hdrs,
        fetch_time=fetch_time,
        success=True,
        error=None,
    )


def _failure_result(url: str, status_code: int | None, fetch_time: float, error: str) -> PageResult:
    return PageResult(
        url=url,
        final_url=url,
        status_code=status_code,
        title=None,
        markdown="",
        fetch_time=fetch_time,
        success=False,
        error=error,
    )


def _max_attempts(proxy_rotator: ProxyRotator | None) -> int:
    if proxy_rotator is None:
        return _DEFAULT_FETCH_ATTEMPTS
    # Never drop below the default transient-retry budget — a small pool would
    # otherwise starve plain 5xx/exception retries that have nothing to do with
    # proxy blocking (e.g. a 2-proxy pool giving only 2 total attempts).
    return max(len(proxy_rotator.settings.proxy_pool), _DEFAULT_FETCH_ATTEMPTS)


async def _fetch_with_retries(
    url: str,
    cfg: CrawlerRunConfig,
    *,
    proxy_rotator: ProxyRotator | None = None,
) -> PageResult:
    """Run a single fetch with retry handling.

    Args:
        url: URL to fetch.
        cfg: Crawl4AI run configuration for the request.
        proxy_rotator: Optional proxy rotator that provides new credentials per attempt.

    Returns:
        Successful page data, or a failure result with the final error.
    """
    domain = urlparse(url).netloc.removeprefix("www.")
    max_attempts = _max_attempts(proxy_rotator)
    for attempt in range(max_attempts):
        t0 = time.monotonic()
        try:
            # Proxy mode rotates credentials before every Crawl4AI request.
            if proxy_rotator is not None:
                creds, wait = await proxy_rotator.next_credentials(domain)
                if wait > 0:
                    await asyncio.sleep(wait)
                cfg_for_attempt = cfg.clone(proxy_config=creds.to_dict()) if creds else cfg
            else:
                cfg_for_attempt = cfg

            async with AsyncWebCrawler(config=_BROWSER_CFG) as crawler:
                result = await crawler.arun(url=url, config=cfg_for_attempt)
            fetch_time = round(time.monotonic() - t0, 2)

            status = result.status_code or 0
            # Only proxy-block signals consume the proxy pool and end as proxy_blocked.
            if proxy_rotator is not None and _is_blocked(result):
                reason = _block_reason(result)
                logger.warning(
                    "fetch blocked, retrying next proxy",
                    url=url,
                    status=status,
                    reason=reason,
                    attempt=attempt + 1,
                )
                if attempt + 1 < max_attempts:
                    backoff = (
                        _retry_after(result)
                        if status == 429
                        else proxy_rotator.settings.block_backoff
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.warning("proxy blocked after all attempts", url=url, status=status)
                return _failure_result(url, status, fetch_time, "proxy_blocked")

            # Non-block HTTP failures keep their original HTTP/error classification.
            if not result.success or status >= 400:
                error = result.error_message or f"HTTP {status}"

                if status == 429:
                    retry_after = _retry_after(result)
                    logger.warning(
                        "fetch 429", url=url, retry_after=retry_after, attempt=attempt + 1
                    )
                    if attempt + 1 < max_attempts:
                        await asyncio.sleep(retry_after)
                        continue

                if status >= 500 and attempt + 1 < max_attempts:
                    backoff = 2**attempt
                    logger.warning(
                        "fetch error retrying",
                        status=status,
                        url=url,
                        backoff=backoff,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(backoff)
                    continue

                logger.warning("fetch failed", url=url, status=result.status_code, error=error)
                return _failure_result(url, result.status_code, fetch_time, error)

            return _build_success_result(url, result, fetch_time)

        except Exception as exc:  # noqa: BLE001
            fetch_time = round(time.monotonic() - t0, 2)
            if attempt + 1 < max_attempts:
                backoff = 2**attempt
                logger.warning("fetch exception retrying", url=url, exc=str(exc), backoff=backoff)
                await asyncio.sleep(backoff)
                continue
            logger.warning("fetch exception", url=url, exc=str(exc))
            return _failure_result(url, None, fetch_time, str(exc))


async def fetch_page(
    url: str,
    css_selector: str | None = None,
    *,
    article_body: bool = True,
    proxy_rotator: ProxyRotator | None = None,
) -> PageResult:
    """Fetch a single URL and return a normalised PageResult.

    Args:
        url: The URL to fetch.
        css_selector: Explicit CSS selector that hard-scopes the whole extraction
            (HTML, metadata, links, markdown) to a region. Overrides article_body
            auto-detection when provided.
        article_body: When True (default) and css_selector is None, a known-site
            article selector is auto-detected and applied as target_elements —
            scoping only the markdown so head metadata (title, date) and full-page
            links survive. Pass article_body=False to always fetch the full page.
        proxy_rotator: Optional proxy rotator. When provided, a new credential is
            selected for each request attempt.

    Returns:
        PageResult with markdown, links, and metadata. Never raises — failures
        are returned as PageResult(success=False, error=...).

    Fallback:
        If a scoped fetch succeeds but returns unusable markdown (e.g. stale
        selector), one full-page fetch is attempted automatically.
    """
    target_elements: list[str] | None = None
    if css_selector is None and article_body:
        target_elements = article_target_elements_for_url(url) or None

    logger.debug("fetch start", url=url, css_selector=css_selector, target_elements=target_elements)
    page = await _fetch_with_retries(
        url, _make_cfg(css_selector, target_elements), proxy_rotator=proxy_rotator
    )

    if (
        (css_selector or target_elements)
        and page.success
        and not _has_usable_scoped_markdown(page.markdown)
    ):
        logger.warning("scoped fetch returned unusable markdown, retrying full page", url=url)
        page = await _fetch_with_retries(url, _RUN_CFG, proxy_rotator=proxy_rotator)

    return page
