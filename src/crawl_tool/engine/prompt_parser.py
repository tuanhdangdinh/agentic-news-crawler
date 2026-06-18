"""Parse a one-shot natural-language crawl description into structured fields."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import anthropic
import jsonschema
import structlog

from crawl_tool.engine.config import MAX_DEPTH_CEILING
from crawl_tool.engine.prompts import render

logger = structlog.get_logger(__name__)

MODEL = "claude-haiku-4-5-20251001"

_PARSED_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "seed_url": {"type": "string"},
        "goal": {"type": "string"},
        "extract_prompt": {"type": "string"},
        "max_depth": {"type": "integer", "minimum": 0, "maximum": MAX_DEPTH_CEILING},
        "max_pages": {"type": "integer"},
        "date_filter": {"type": "string"},
        "include_undated": {"type": "boolean"},
        "same_domain": {"type": "boolean"},
        "include_patterns": {"type": "array", "items": {"type": "string"}},
        "exclude_patterns": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


class PromptParseError(Exception):
    """Raised when a one-shot prompt cannot be parsed into a usable seed_url."""


def _strip_fences(text: str) -> str:
    """Strip markdown code fences Claude sometimes adds despite instructions."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return match.group(1).strip() if match else text


async def parse_crawl_prompt(prompt: str, client: anthropic.AsyncAnthropic | None = None) -> dict:
    """Parse a one-shot natural-language crawl description into structured fields.

    Args:
        prompt: Natural-language description of the whole crawl.
        client: Shared Anthropic client; a new one is created if not provided.

    Returns:
        A dict containing only the keys the prompt gave evidence for.

    Raises:
        PromptParseError: Response is unusable or has no absolute seed URL.
    """
    client = client or anthropic.AsyncAnthropic()
    user_content = render("parse_prompt.j2", prompt=prompt)

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_content}],
    )

    if not response.content or response.stop_reason == "max_tokens":
        logger.warning("parse_crawl_prompt: truncated response", stop_reason=response.stop_reason)
        raise PromptParseError("empty or truncated response from Claude")

    raw = _strip_fences(response.content[0].text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("parse_crawl_prompt: JSON parse error", exc=str(exc))
        raise PromptParseError(f"JSON parse error: {exc}") from exc

    try:
        jsonschema.validate(instance=parsed, schema=_PARSED_PROMPT_SCHEMA)
    except jsonschema.ValidationError as exc:
        logger.warning("parse_crawl_prompt: schema validation failed", error=exc.message)
        raise PromptParseError(f"schema validation failed: {exc.message}") from exc

    seed_url = parsed.get("seed_url")
    if not seed_url:
        raise PromptParseError("no seed url found in prompt")
    url_parts = urlparse(seed_url)
    if not url_parts.scheme or not url_parts.netloc:
        raise PromptParseError(f"seed url is not a valid absolute URL: {seed_url!r}")

    logger.debug("parse_crawl_prompt done", fields=list(parsed.keys()))
    return parsed
