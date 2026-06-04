"""LLM agent loop — observe, decide, act, update cycle."""

from __future__ import annotations

import fnmatch
import logging
import re
from datetime import date
from urllib.parse import urlparse

import anthropic
from pydantic import BaseModel, Field, computed_field

from src.crawler import fetch_page
from src.extractor import extract as extractor_extract
from src.extractor import infer_schema
from src.models import PageResult
from src.prompts import render

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
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
                "schema": {"type": "object", "description": "Optional JSON Schema to validate output"},
            },
            "required": ["prompt"],
        },
    },
]


# ---------------------------------------------------------------------------
# Config and state
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    """User-supplied parameters for a crawl run."""

    goal: str = ""
    max_depth: int = 1
    max_pages: int = 100
    token_budget: int = 500_000
    same_domain: bool = True
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    model: str = MODEL
    extract_prompt: str = ""
    extract_schema: dict | None = None
    date_filter: str = ""
    include_undated: bool = True


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
        return self.total_input_tokens + self.total_output_tokens


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def _canonical(url: str) -> str:
    """Strip fragment for dedup purposes."""
    p = urlparse(url)
    return p._replace(fragment="").geturl()


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
) -> str:
    """Execute a tool call from the agent and return a result string."""
    logger.debug("tool call: %s inputs=%s", name, inputs)

    if name == "add_to_frontier":
        if "url" not in inputs:
            logger.warning("add_to_frontier called without url field — inputs=%s", inputs)
            return "error: missing required field 'url'"
        url = _canonical(inputs["url"])
        next_depth = current_depth + 1
        if next_depth > config.max_depth:
            logger.debug("guardrail: depth %d > max %d — blocked %s", next_depth, config.max_depth, url)
            return f"skipped (depth {next_depth} > max {config.max_depth})"
        if url in state.visited:
            logger.debug("guardrail: already visited — blocked %s", url)
            return "skipped (already visited)"
        if not _allowed(url, seed_url, config):
            logger.debug("guardrail: pattern/domain filter — blocked %s", url)
            return "skipped (blocked by guardrail)"
        if any(u == url for u, _ in state.frontier):
            logger.debug("guardrail: already in frontier — skipped %s", url)
            return "skipped (already in frontier)"
        state.frontier.append((url, next_depth))
        logger.info("frontier +%s (depth %d)", url, next_depth)
        return f"added at depth {next_depth}"

    if name == "mark_visited":
        url = _canonical(inputs["url"])
        state.visited.add(url)
        return "marked visited"

    if name == "finish":
        reachable = [u for u, d in state.frontier if d <= config.max_depth]
        if reachable:
            logger.info("finish rejected: %d reachable URLs still in frontier", len(reachable))
            return (
                f"finish rejected: {len(reachable)} URLs still in the frontier at reachable depth "
                f"— the crawler will fetch them automatically; do not call finish yet"
            )
        if min_articles > 0 and len(state.article_pages) < min_articles:
            queued = len(state.frontier)
            collected = len(state.article_pages)
            logger.info(
                "finish rejected: need %d article pages, have %d, queued %d",
                min_articles,
                collected,
                queued,
            )
            return (
                f"finish rejected: goal requires {min_articles} article pages, "
                f"only {collected} collected, {queued} queued"
            )
        state.finished = True
        state.finish_reason = inputs.get("reason", "")
        state.stop_reason = "agent_finish"
        state.frontier_at_finish = [u for u, _ in state.frontier]
        logger.info("agent finished: %s", state.finish_reason)
        return "crawl terminated"

    if name == "extract":
        if current_page is None:
            return "error: no current page available for extraction"
        prompt = inputs.get("prompt", config.extract_prompt)
        schema = inputs.get("schema") or config.extract_schema
        result = await extractor_extract(current_page, prompt, schema)
        if "error" in result:
            logger.warning("extraction error on %s: %s", current_page.url, result["error"])
            current_page.metadata["extraction_error"] = result["error"]
        else:
            current_page.metadata["extracted"] = result
            logger.info("extracted %d fields from %s", len(result), current_page.url)
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
    user_content = render(
        "user_turn.j2",
        url=page.final_url,
        title=page.title,
        depth=depth,
        max_depth=config.max_depth,
        markdown=page.markdown,
        links_internal=page.links_internal,
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
            "claude response: stop_reason=%s input_tokens=%d output_tokens=%d total=%d",
            response.stop_reason,
            response.usage.input_tokens,
            response.usage.output_tokens,
            state.tokens_used,
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
                )
                if result.startswith("finish rejected:"):
                    finish_rejected = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        if response.stop_reason == "end_turn" or not tool_results:
            break

        if state.finished:
            break

        if finish_rejected:
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
    else:
        logger.warning("max tool turns reached for page: %s", page.final_url)


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

    if config.extract_prompt and config.extract_schema is None:
        logger.info("inferring extraction schema from prompt")
        config.extract_schema = await infer_schema(config.extract_prompt)
        logger.info("inferred schema with %d properties", len(config.extract_schema.get("properties", {})))

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
            logger.info("max_pages (%d) reached — stopping", config.max_pages)
            state.stop_reason = "max_pages"
            break
        if state.tokens_used >= config.token_budget:
            logger.info("token_budget (%d) exhausted — stopping", config.token_budget)
            state.stop_reason = "token_budget"
            break

        url, depth = state.frontier.pop(0)

        if url in state.visited:
            continue

        # OBSERVE — fetch the page
        logger.info("fetching [depth=%d] %s", depth, url)
        page = await fetch_page(url)
        state.visited.add(url)

        if not page.success:
            logger.warning("fetch failed: %s — %s", url, page.error)
            continue

        page.metadata["depth"] = depth
        state.pages.append(page)
        if _is_article_page(page):
            state.article_pages.append(page.final_url)
        print(
            f"  [{len(state.pages):>3}] depth={depth} "
            f"chars={len(page.markdown):>6} "
            f"links={len(page.links_internal):>3} "
            f"{url}"
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
            logger.debug("auto-extracting from %s", url)
            result = await extractor_extract(page, config.extract_prompt, config.extract_schema)
            if "error" in result:
                page.metadata["extraction_error"] = result["error"]
                logger.warning("extraction error on %s: %s", url, result["error"])
            else:
                page.metadata["extracted"] = result
                logger.info("extracted %d fields from %s", len(result), url)

    if not state.stop_reason:
        state.stop_reason = "agent_finish" if state.finished else "frontier_empty"
    if not state.frontier_at_finish:
        state.frontier_at_finish = [u for u, _ in state.frontier]
    return state
