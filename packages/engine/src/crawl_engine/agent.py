"""LLM agent loop — observe, decide, act, update cycle."""

from __future__ import annotations

import fnmatch
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlparse

import anthropic
import structlog
from pydantic import BaseModel, Field, computed_field

from crawl_engine.config import (
    MAX_DEPTH_CEILING as MAX_DEPTH_CEILING,
)
from crawl_engine.config import (
    MODEL as MODEL,
)
from crawl_engine.config import AgentConfig
from crawl_engine.crawler import fetch_page, looks_like_article_url
from crawl_engine.date_filter import detect_page_date, is_in_range, parse_date_filter
from crawl_engine.extractor import extract as extractor_extract
from crawl_engine.extractor import infer_schema
from crawl_engine.models import PageResult
from crawl_engine.prompts import render
from crawl_engine.schema_registry import match_registered_schema

logger = structlog.get_logger(__name__)

MAX_TOOL_TURNS_PER_PAGE = 5

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "add_to_frontier",
        "description": "Queue a URL to be crawled next. Only add URLs relevant to the goal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute URL to crawl"},
                "reason": {"type": "string", "description": "Why this URL is relevant"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "mark_visited",
        "description": "Mark a URL as seen so it will never be fetched.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "finish",
        "description": "Terminate the crawl. Call when the goal is satisfied or no relevant pages remain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the crawl is complete"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "extract",
        "description": "Extract structured fields from the current page using a natural-language prompt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What fields to extract"},
                "schema": {
                    "type": "object",
                    "description": "Optional JSON Schema to validate output",
                },
            },
            "required": ["prompt"],
        },
    },
]


# ---------------------------------------------------------------------------
# Config and state
# ---------------------------------------------------------------------------


class CrawlState(BaseModel):
    """Mutable state updated throughout the agent loop."""

    frontier: list[tuple[str, int]] = Field(default_factory=list)
    visited: set[str] = Field(default_factory=set)
    pages: list[PageResult] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    finished: bool = False
    finish_reason: str = ""
    stop_reason: str = ""
    article_pages: list[str] = Field(default_factory=list)
    frontier_at_finish: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    @computed_field
    @property
    def tokens_used(self) -> int:
        """Return the total Anthropic API tokens used by the crawl.

        Returns:
            Sum of input and output tokens recorded in the crawl state.
        """
        return self.total_input_tokens + self.total_output_tokens


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


def _canonical(url: str) -> str:
    """Strip fragment and sort query parameters for dedup purposes."""
    p = urlparse(url)
    query = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
    return p._replace(query=query, fragment="").geturl()


def _parse_min_articles(goal: str) -> int:
    """Return the explicit minimum article count requested by the goal."""
    if not goal:
        return 0

    number_pattern = r"\d+|" + "|".join(_NUMBER_WORDS)
    patterns = [
        rf"(?:at\s+least|minimum|>=)\s+({number_pattern})\s+(?:\w+\s+){{0,4}}articles?",
        rf"(?:fetch|read|collect|get)\s+(?:\w+\s+){{0,4}}({number_pattern})\s+(?:\w+\s+){{0,4}}articles?",
        rf"\b({number_pattern})\s+(?:\w+\s+){{0,4}}articles?",
    ]

    for pattern in patterns:
        match = re.search(pattern, goal, re.IGNORECASE)
        if match:
            raw = match.group(1).lower()
            return int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    return 0


def _is_article_page(page: PageResult) -> bool:
    """Return True when metadata or URL strongly indicates an article page."""
    metadata = page.metadata or {}
    if metadata.get("article:published_time"):
        return True
    # URL-based article classification covers known site selectors plus generic
    # article/detail URL patterns for unsupported sites.
    if looks_like_article_url(page.final_url):
        return True
    # Fallback for sites not yet in the selector map.
    path = urlparse(page.final_url).path
    return bool(re.search(r"/[^/]+-\d{9,}\.chn$", path))


def _same_domain(seed: str, url: str) -> bool:
    return urlparse(seed).netloc == urlparse(url).netloc


def _allowed(url: str, seed: str, config: AgentConfig) -> bool:
    """Return True if the URL passes all hard guardrails."""
    if config.same_domain and not _same_domain(seed, url):
        return False
    if config.exclude_patterns and any(fnmatch.fnmatch(url, p) for p in config.exclude_patterns):
        return False
    return not (
        config.include_patterns
        and not any(fnmatch.fnmatch(url, p) for p in config.include_patterns)
    )


def _is_current_page_link(url: str, page: PageResult | None) -> bool:
    """Return True when the URL was extracted from the current page.

    The model sees links as text and can accidentally rewrite them. When a
    current page is available, only allow exact extracted links, after the same
    fragment-stripping canonicalization used for de-duplication.
    """
    if page is None:
        return True
    return url in {_canonical(link) for link in page.links_internal}


def _article_candidate_links(links: list[str]) -> list[str]:
    """Return links matching known article URL patterns."""
    return [link for link in links if looks_like_article_url(link)]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


async def _execute_tool(
    name: str,
    inputs: dict,
    state: CrawlState,
    config: AgentConfig,
    seed_url: str,
    current_depth: int,
    current_page: PageResult | None = None,
    min_articles: int = 0,
    client: anthropic.AsyncAnthropic | None = None,
) -> str:
    """Execute a tool call from the agent and return a result string."""
    logger.debug("tool call", name=name, inputs=inputs)

    if name == "add_to_frontier":
        if "url" not in inputs:
            logger.warning("add_to_frontier called without url field", inputs=inputs)
            return "error: missing required field 'url'"
        url = _canonical(inputs["url"])
        next_depth = current_depth + 1
        if next_depth > config.max_depth:
            logger.debug(
                "guardrail: depth exceeded",
                next_depth=next_depth,
                max_depth=config.max_depth,
                url=url,
            )
            return f"skipped (depth {next_depth} > max {config.max_depth})"
        if url in state.visited:
            logger.debug("guardrail: already visited", url=url)
            return "skipped (already visited)"
        if not _allowed(url, seed_url, config):
            logger.debug("guardrail: blocked by filter", url=url)
            return "skipped (blocked by guardrail)"
        if not _is_current_page_link(url, current_page):
            logger.debug("guardrail: not in current page links", url=url)
            return "skipped (not found in current page links)"
        if any(u == url for u, _ in state.frontier):
            logger.debug("guardrail: already in frontier", url=url)
            return "skipped (already in frontier)"
        state.frontier.append((url, next_depth))
        logger.info("frontier add", url=url, depth=next_depth)
        return f"added at depth {next_depth}"

    if name == "mark_visited":
        url = _canonical(inputs["url"])
        state.visited.add(url)
        return "marked visited"

    if name == "finish":
        reachable = [u for u, d in state.frontier if d <= config.max_depth]
        if reachable:
            logger.info("finish rejected: reachable URLs in frontier", count=len(reachable))
            return (
                f"finish rejected: {len(reachable)} URLs still in the frontier at reachable depth "
                f"— the crawler will fetch them automatically; do not call finish yet"
            )
        if min_articles > 0 and len(state.article_pages) < min_articles:
            queued = len(state.frontier)
            collected = len(state.article_pages)
            logger.info(
                "finish rejected: article count",
                need=min_articles,
                have=collected,
                queued=queued,
            )
            return (
                f"finish rejected: goal requires {min_articles} article pages, "
                f"only {collected} collected, {queued} queued"
            )
        state.finished = True
        state.finish_reason = inputs.get("reason", "")
        state.stop_reason = "agent_finish"
        state.frontier_at_finish = [u for u, _ in state.frontier]
        logger.info("agent finished", reason=state.finish_reason)
        return "crawl terminated"

    if name == "extract":
        if current_page is None:
            return "error: no current page available for extraction"
        prompt = inputs.get("prompt", config.extract_prompt)
        explicit_schema = inputs.get("schema")
        schema = explicit_schema or config.extract_schema
        lenient = explicit_schema is None and config.extract_schema_inferred
        if schema is None:
            registered = match_registered_schema(prompt)
            if registered is not None:
                schema_name, schema = registered
                logger.info("registered extraction schema selected", schema=schema_name)
            else:
                logger.info("inferring extraction schema from tool prompt")
                schema = await infer_schema(prompt, client=client)
                config.extract_schema_inferred = True
                lenient = True
            config.extract_schema = schema
        result = await extractor_extract(
            current_page, prompt, schema, client=client, lenient=lenient
        )
        if "error" in result:
            logger.warning("extraction error", url=current_page.url, error=result["error"])
            current_page.metadata["extraction_error"] = result["error"]
        else:
            current_page.metadata["extracted"] = result
            logger.info("extracted", fields=len(result), url=current_page.url)
        return str(result)

    return f"unknown tool: {name}"


# ---------------------------------------------------------------------------
# Per-page agent turn
# ---------------------------------------------------------------------------


async def _agent_turn(
    client: anthropic.AsyncAnthropic,
    system_prompt: str,
    page: PageResult,
    depth: int,
    state: CrawlState,
    config: AgentConfig,
    seed_url: str,
    min_articles: int = 0,
) -> None:
    """Run the observe-decide-act cycle for one page."""
    markdown = page.markdown
    if config.max_chars > 0 and len(markdown) > config.max_chars:
        markdown = markdown[: config.max_chars]
        logger.debug(
            "markdown truncated",
            chars=config.max_chars,
            original=len(page.markdown),
            url=page.final_url,
        )

    user_content = render(
        "user_turn.j2",
        url=page.final_url,
        title=page.title,
        depth=depth,
        max_depth=config.max_depth,
        markdown=markdown,
        links_internal=page.links_internal,
        article_candidate_links=_article_candidate_links(page.links_internal),
        pages_count=len(state.pages),
        frontier_count=len(state.frontier),
        frontier_reachable=len([u for u, d in state.frontier if d <= config.max_depth]),
        visited_count=len(state.visited),
        article_pages_count=len(state.article_pages),
        min_articles=min_articles,
        tokens_used=state.tokens_used,
        token_budget=config.token_budget,
    )

    messages: list[dict] = [{"role": "user", "content": user_content}]

    # Tool-use loop — keep calling Claude until it stops requesting tools
    for _ in range(MAX_TOOL_TURNS_PER_PAGE):
        response = await client.messages.create(
            model=config.model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        state.total_input_tokens += response.usage.input_tokens
        state.total_output_tokens += response.usage.output_tokens
        logger.debug(
            "claude response",
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total=state.tokens_used,
        )

        tool_results = []
        finish_rejected = False
        for block in response.content:
            if block.type == "tool_use":
                result = await _execute_tool(
                    block.name,
                    block.input,
                    state,
                    config,
                    seed_url,
                    depth,
                    page,
                    min_articles,
                    client=client,
                )
                if result.startswith("finish rejected:"):
                    finish_rejected = True
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

        if response.stop_reason == "end_turn" or not tool_results:
            break

        if state.finished:
            break

        if finish_rejected:
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
    else:
        logger.warning("max tool turns reached", url=page.final_url)


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------


async def run_agent(seed_url: str, config: AgentConfig) -> CrawlState:
    """Run the full agent crawl loop.

    Args:
        seed_url: The URL to start crawling from.
        config: Crawl parameters and guardrails.

    Returns:
        CrawlState with all collected pages and run statistics.
    """
    client = anthropic.AsyncAnthropic()
    state = CrawlState()
    state.frontier.append((_canonical(seed_url), 0))
    min_articles = _parse_min_articles(config.goal)

    date_range = None
    if config.date_filter:
        date_range = parse_date_filter(config.date_filter)
        logger.info(
            "date filter active",
            filter=config.date_filter,
            from_date=str(date_range[0]),
            to_date=str(date_range[1]),
            include_undated=config.include_undated,
        )

    if config.extract_prompt and config.extract_schema is None:
        registered = match_registered_schema(config.extract_prompt)
        if registered is not None:
            schema_name, config.extract_schema = registered
            logger.info("registered extraction schema selected", schema=schema_name)
        else:
            logger.info("inferring extraction schema from prompt")
            config.extract_schema = await infer_schema(config.extract_prompt, client=client)
            config.extract_schema_inferred = True
            logger.info(
                "inferred schema",
                properties=len(config.extract_schema.get("properties", {})),
            )

    system_prompt = render(
        "system.j2",
        goal=config.goal,
        max_depth=config.max_depth,
        max_pages=config.max_pages,
        same_domain=config.same_domain,
        extract_prompt=config.extract_prompt,
        today=date.today().isoformat(),
    )

    while state.frontier and not state.finished:
        # Hard budget guards
        if len(state.pages) >= config.max_pages:
            logger.info("max_pages reached", max_pages=config.max_pages)
            state.stop_reason = "max_pages"
            break
        if state.tokens_used >= config.token_budget:
            logger.info("token_budget exhausted", budget=config.token_budget)
            state.stop_reason = "token_budget"
            break

        url, depth = state.frontier.pop(0)

        if url in state.visited:
            continue

        # OBSERVE — fetch the page
        logger.info("fetching", depth=depth, url=url)
        page = await fetch_page(url, css_selector=config.css_selector or None)
        state.visited.add(url)

        if not page.success:
            logger.warning("fetch failed", url=url, error=page.error)
            continue

        if date_range is not None and _is_article_page(page):
            page_date = detect_page_date(page)
            if not is_in_range(page_date, *date_range, include_undated=config.include_undated):
                logger.info("page dropped: outside date range", url=url, page_date=str(page_date))
                continue

        page.metadata["depth"] = depth
        state.pages.append(page)
        if _is_article_page(page):
            state.article_pages.append(page.final_url)
        logger.info(
            "page collected",
            index=len(state.pages),
            depth=depth,
            status=page.status_code,
            fetch_time=page.fetch_time,
            chars=len(page.markdown),
            links=len(page.links_internal),
            url=url,
        )

        # DECIDE + ACT — agent chooses which links to follow
        await _agent_turn(client, system_prompt, page, depth, state, config, seed_url, min_articles)

        # Auto-extract if Claude didn't call the extract tool itself
        if (
            config.extract_prompt
            and _is_article_page(page)
            and "extracted" not in page.metadata
            and "extraction_error" not in page.metadata
        ):
            logger.debug("auto-extracting", url=url)
            result = await extractor_extract(
                page,
                config.extract_prompt,
                config.extract_schema,
                client=client,
                lenient=config.extract_schema_inferred,
            )
            if "error" in result:
                page.metadata["extraction_error"] = result["error"]
                logger.warning("extraction error", url=url, error=result["error"])
            else:
                page.metadata["extracted"] = result
                logger.info("extracted", fields=len(result), url=url)

    if not state.stop_reason:
        state.stop_reason = "agent_finish" if state.finished else "frontier_empty"
    if not state.frontier_at_finish:
        state.frontier_at_finish = [u for u, _ in state.frontier]
    return state
