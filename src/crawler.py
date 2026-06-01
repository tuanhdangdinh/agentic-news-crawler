"""Thin async wrapper around Crawl4AI."""

from __future__ import annotations

from dataclasses import dataclass, field

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

_BROWSER_CFG = BrowserConfig(browser_type="chromium", headless=True)

_RUN_CFG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    check_robots_txt=True,
    markdown_generator=DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.6)
    ),
)


@dataclass
class PageResult:
    """Normalised output of a single page fetch."""

    url: str
    final_url: str
    status_code: int | None
    title: str | None
    markdown: str
    raw_markdown: str | None
    html: str | None
    links_internal: list[str] = field(default_factory=list)
    links_external: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    success: bool = True
    error: str | None = None


def _extract_links(links_dict: dict) -> tuple[list[str], list[str]]:
    """Pull href strings from Crawl4AI's links dict."""
    internal = [lnk.get("href", "") for lnk in links_dict.get("internal", []) if lnk.get("href")]
    external = [lnk.get("href", "") for lnk in links_dict.get("external", []) if lnk.get("href")]
    return internal, external


async def fetch_page(url: str, css_selector: str | None = None) -> PageResult:
    """Fetch a single URL and return a normalised PageResult.

    Args:
        url: The URL to fetch.
        css_selector: Optional CSS selector to scope content extraction.

    Returns:
        PageResult with markdown, links, and metadata. Never raises — failures
        are returned as PageResult(success=False, error=...).
    """
    cfg = _RUN_CFG
    if css_selector:
        cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            check_robots_txt=True,
            css_selector=css_selector,
            markdown_generator=DefaultMarkdownGenerator(
                content_filter=PruningContentFilter(threshold=0.6)
            ),
        )

    try:
        async with AsyncWebCrawler(config=_BROWSER_CFG) as crawler:
            result = await crawler.arun(url=url, config=cfg)

        if not result.success:
            return PageResult(
                url=url,
                final_url=url,
                status_code=result.status_code,
                title=None,
                markdown="",
                raw_markdown=None,
                html=None,
                success=False,
                error=result.error_message or "crawl failed",
            )

        md = result.markdown
        markdown = (md.fit_markdown or md.raw_markdown) if md else ""
        raw_markdown = md.raw_markdown if md else None

        internal, external = _extract_links(result.links or {})

        metadata = result.metadata or {}
        title = metadata.get("title") or metadata.get("og:title")

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
            success=True,
            error=None,
        )

    except Exception as exc:  # noqa: BLE001
        return PageResult(
            url=url,
            final_url=url,
            status_code=None,
            title=None,
            markdown="",
            raw_markdown=None,
            html=None,
            success=False,
            error=str(exc),
        )
