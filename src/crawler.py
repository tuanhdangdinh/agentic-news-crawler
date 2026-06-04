"""Thin async wrapper around Crawl4AI."""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlparse

import structlog
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from src.models import PageResult

logger = structlog.get_logger(__name__)

_BROWSER_CFG = BrowserConfig(browser_type="chromium", headless=True)

_RUN_CFG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    check_robots_txt=True,
    markdown_generator=DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.6)
    ),
)

# Maps netloc (without www.) → (article URL pattern, CSS selector for body).
# When a URL matches the pattern, the selector scopes the fetch to the article
# body only, cutting 60–82% of tokens on article pages.
_ARTICLE_SELECTORS: dict[str, tuple[str, str]] = {
    "cafef.vn":     (r"/[^/]+-\d{9,}\.chn$",  ".detail-content"),
    "tuoitre.vn":   (r"/[^/]+-\d{12,}\.htm$", ".detail-content"),
    "vneconomy.vn": (r"/[^/]{30,}\.htm$",      ".block-detail-page"),
}


def article_selector_for_url(url: str) -> str | None:
    """Return the article-body CSS selector for a known site URL, or None.

    This is the single source of truth for URL-based article classification
    used by both the crawler (scoped fetch) and the agent loop (article tagging).
    """
    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.")
    entry = _ARTICLE_SELECTORS.get(domain)
    if entry is None:
        return None
    pattern, selector = entry
    return selector if re.search(pattern, parsed.path) else None


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
        css_selector=css_selector,
        target_elements=target_elements,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.6)
        ),
    )


def _extract_links(links_dict: dict) -> tuple[list[str], list[str]]:
    """Pull href strings from Crawl4AI's links dict."""
    internal = [lnk.get("href", "") for lnk in links_dict.get("internal", []) if lnk.get("href")]
    external = [lnk.get("href", "") for lnk in links_dict.get("external", []) if lnk.get("href")]
    return internal, external


async def _fetch_with_retries(url: str, cfg: CrawlerRunConfig) -> PageResult:
    """Run a single fetch with up to 3 retries on 5xx / exception."""
    max_retries = 3
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            async with AsyncWebCrawler(config=_BROWSER_CFG) as crawler:
                result = await crawler.arun(url=url, config=cfg)
            fetch_time = round(time.monotonic() - t0, 2)

            if not result.success:
                status = result.status_code or 0

                if status == 429:
                    resp_hdrs = getattr(result, "response_headers", {}) or {}
                    retry_after = int(resp_hdrs.get("retry-after", resp_hdrs.get("Retry-After", 60)))
                    logger.warning("fetch 429", url=url, retry_after=retry_after, attempt=attempt + 1)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_after)
                        continue

                if status >= 500 and attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    logger.warning("fetch error retrying", status=status, url=url, backoff=backoff, attempt=attempt + 1)
                    await asyncio.sleep(backoff)
                    continue

                logger.warning("fetch failed", url=url, status=result.status_code, error=result.error_message)
                return PageResult(
                    url=url,
                    final_url=url,
                    status_code=result.status_code,
                    title=None,
                    markdown="",
                    fetch_time=fetch_time,
                    success=False,
                    error=result.error_message or "crawl failed",
                )

            md = result.markdown
            markdown = (md.fit_markdown or md.raw_markdown) if md else ""
            raw_markdown = md.raw_markdown if md else None
            internal, external = _extract_links(result.links or {})
            metadata = result.metadata or {}
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

        except Exception as exc:  # noqa: BLE001
            fetch_time = round(time.monotonic() - t0, 2)
            if attempt < max_retries - 1:
                backoff = 2 ** attempt
                logger.warning("fetch exception retrying", url=url, exc=str(exc), backoff=backoff)
                await asyncio.sleep(backoff)
                continue
            logger.warning("fetch exception", url=url, exc=str(exc))
            return PageResult(
                url=url,
                final_url=url,
                status_code=None,
                title=None,
                markdown="",
                fetch_time=fetch_time,
                success=False,
                error=str(exc),
            )


async def fetch_page(
    url: str,
    css_selector: str | None = None,
    *,
    article_body: bool = True,
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

    Returns:
        PageResult with markdown, links, and metadata. Never raises — failures
        are returned as PageResult(success=False, error=...).

    Fallback:
        If a scoped fetch succeeds but returns empty markdown (e.g. stale
        selector), one full-page fetch is attempted automatically.
    """
    target_elements: list[str] | None = None
    if css_selector is None and article_body:
        selector = article_selector_for_url(url)
        if selector:
            target_elements = [selector]

    logger.debug("fetch start", url=url, css_selector=css_selector, target_elements=target_elements)
    page = await _fetch_with_retries(url, _make_cfg(css_selector, target_elements))

    if (css_selector or target_elements) and page.success and not page.markdown:
        logger.warning("scoped fetch returned empty markdown, retrying full page", url=url)
        page = await _fetch_with_retries(url, _RUN_CFG)

    return page
