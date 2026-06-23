"""Execute a crawl request and shape the result payload.

This is the shared seam between the CLI and the HTTP service: both turn a
CrawlRequest into a result payload without knowing about each other.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crawl_tool.engine.agent import CrawlState, run_agent
from crawl_tool.engine.config import AgentConfig
from crawl_tool.engine.contract import CrawlRequest
from crawl_tool.engine.crawler import fetch_page
from crawl_tool.engine.models import PageResult
from crawl_tool.engine.proxy import ProxyRotator, ProxySettings


def _page_record(page: PageResult) -> dict:
    return page.model_dump(exclude={"html", "raw_markdown"})


def _result_payload(pages: list[PageResult], run_meta: dict) -> dict:
    return {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_pages": len(pages),
            "successful": sum(page.success for page in pages),
            "failed": sum(not page.success for page in pages),
            **run_meta,
        },
        "pages": [_page_record(page) for page in pages],
    }


def _agent_run_meta(seed_url: str, config: AgentConfig, state: CrawlState) -> dict:
    return {
        "seed_url": seed_url,
        "goal": config.goal,
        "max_depth": config.max_depth,
        "max_pages": config.max_pages,
        "pages_collected": len(state.pages),
        "article_pages_collected": len(state.article_pages),
        "article_pages": list(state.article_pages),
        "urls_visited": len(state.visited),
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "finish_reason": state.finish_reason,
        "stop_reason": state.stop_reason,
        "frontier_at_finish": list(state.frontier_at_finish),
    }


def _direct_run_meta(seed_url: str, page: PageResult) -> dict:
    return {
        "seed_url": seed_url,
        "goal": "",
        "max_depth": 0,
        "max_pages": 1,
        "pages_collected": int(page.success),
        "urls_visited": 1,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "finish_reason": "single page fetched",
    }


async def execute(request: CrawlRequest, state: CrawlState) -> dict:
    """Run a crawl from a request, writing progress into state.

    Args:
        request: Validated crawl request.
        state: Crawl state populated by the agent path for live progress.

    Returns:
        Result payload with meta and pages.
    """
    settings = ProxySettings.from_env()
    proxy_rotator: ProxyRotator | None = ProxyRotator(settings) if settings.enabled else None
    config = request.to_agent_config()
    seed = request.seed_url
    if not config.goal and not config.extract_prompt:
        page = await fetch_page(
            seed, css_selector=config.css_selector or None, proxy_rotator=proxy_rotator
        )
        return _result_payload([page], _direct_run_meta(seed, page))
    await run_agent(seed, config, state=state, proxy_rotator=proxy_rotator)
    return _result_payload(state.pages, _agent_run_meta(seed, config, state))
