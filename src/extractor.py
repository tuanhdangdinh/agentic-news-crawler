"""Structured extraction via Claude + JSON Schema validation."""

from __future__ import annotations

import json
import re

import anthropic
import jsonschema
import structlog

from src.models import PageResult
from src.prompts import render

logger = structlog.get_logger(__name__)

MODEL = "claude-haiku-4-5-20251001"


def _strip_fences(text: str) -> str:
    """Strip markdown code fences Claude sometimes adds despite instructions."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return match.group(1).strip() if match else text


def _validate(data: dict, schema: dict) -> tuple[bool, str]:
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True, ""
    except jsonschema.ValidationError as exc:
        return False, exc.message


async def infer_schema(prompt: str) -> dict:
    """Convert a natural-language extraction request into a JSON Schema.

    Args:
        prompt: Natural-language description of fields to extract.

    Returns:
        A JSON Schema dict with type "object" and a properties block.
    """
    client = anthropic.AsyncAnthropic()
    user_content = render("infer_schema.j2", prompt=prompt)

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_content}],
    )

    if not response.content or response.stop_reason == "max_tokens":
        logger.warning("infer_schema: truncated response", stop_reason=response.stop_reason)
        return {"type": "object", "properties": {}}
    raw = _strip_fences(response.content[0].text)
    logger.debug("infer_schema response", chars=len(raw))
    try:
        schema = json.loads(raw)
        schema.pop("required", None)
        for prop in schema.get("properties", {}).values():
            t = prop.get("type")
            if isinstance(t, str):
                prop["type"] = [t, "null"]  # allow null when field not present in article
        logger.debug("infer_schema done", properties=len(schema.get("properties", {})))
        return schema
    except json.JSONDecodeError as exc:
        logger.warning("infer_schema JSON parse error", exc=str(exc))
        return {"type": "object", "properties": {}}


async def extract(
    page: PageResult,
    prompt: str,
    schema: dict | None = None,
) -> dict:
    """Extract structured data from a fetched page.

    Args:
        page: Fetched page whose markdown is the primary extraction input.
        prompt: Natural-language instruction describing which fields to extract.
        schema: JSON Schema to validate output against. When None, infer_schema
            is called first to derive one from the prompt.

    Returns:
        Validated extraction result on success.
        {"error": "<message>", "raw": "<claude output>"} on parse or validation failure.
        Never raises.
    """
    if not page.markdown:
        return {"error": "page has no markdown content", "raw": ""}

    if schema is None:
        logger.debug("extract: inferring schema")
        schema = await infer_schema(prompt)

    logger.debug("extract start", url=page.url, prompt=prompt[:60], schema_props=len(schema.get("properties", {})))
    client = anthropic.AsyncAnthropic()
    user_content = render(
        "extract.j2",
        prompt=prompt,
        schema_json=json.dumps(schema, indent=2, ensure_ascii=False),
        markdown=page.markdown,
    )

    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract: Claude API error", url=page.url, exc=str(exc))
        return {"error": str(exc), "raw": ""}

    if not response.content or response.stop_reason == "max_tokens":
        logger.warning("extract: truncated response", url=page.url, stop_reason=response.stop_reason)
        return {"error": "empty or truncated response from Claude", "raw": ""}
    raw = _strip_fences(response.content[0].text)
    logger.debug("extract response", chars=len(raw))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("extract: JSON parse error", url=page.url, exc=str(exc))
        return {"error": f"JSON parse error: {exc}", "raw": raw}

    valid, error_msg = _validate(data, schema)
    if not valid:
        logger.warning("extract: schema validation failed", url=page.url, error=error_msg)
        return {"error": f"schema validation failed: {error_msg}", "raw": raw}

    return data
