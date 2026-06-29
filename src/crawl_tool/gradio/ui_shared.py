"""Shared helpers and sample data for all crawl UI pages."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import gradio as gr
import httpx

from crawl_tool.gradio.client import (
    download_result,
    poll_until_done,
    start_crawl,
)
from crawl_tool.gradio.ui_results import build_result_table, render_result_table_html

# Short labels keep the UI scannable while each chip inserts the complete value.
_SEED_URL_SAMPLES = [
    ("CafeF", "https://cafef.vn"),
    ("VnEconomy", "https://vneconomy.vn"),
    ("Vietstock", "https://vietstock.vn"),
    ("VnExpress", "https://vnexpress.net/kinh-doanh"),
    ("Tuoi Tre", "https://tuoitre.vn/kinh-doanh"),
]

_GOAL_SAMPLES = [
    ("Recent banking", "Collect the 20 most recent banking articles"),
    ("Stock market", "Find all recent stock market news"),
    ("Earnings reports", "Get the top earnings-report articles"),
    ("USD/VND", "Gather articles about USD/VND exchange rate"),
]

_EXTRACT_PROMPT_SAMPLES = [
    ("Article basics", "Extract title, publish date, author, and one-sentence summary"),
    (
        "Financial facts",
        "Extract title, publish date, stock tickers, and key financial figures",
    ),
    ("Dates only", "Extract article title, URL, and publish date only"),
]

_DATE_FILTER_SAMPLES = [
    ("7 days", "last 7 days"),
    ("30 days", "last 30 days"),
    ("Since date", "since 2024-01-01"),
    ("Date range", "between 2024-01-01 and 2024-12-31"),
]

_CSS_SELECTOR_SAMPLES = [
    ("Main article", "article.main-content"),
    ("Detail content", ".detail-content"),
    ("Article body ID", "#article-body"),
    ("Article body class", ".article__body"),
]


def _parse_patterns(value: str | None) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def _parse_schema(value: str | None) -> dict | None:
    if not value or not value.strip():
        return None
    try:
        schema = json.loads(value)
    except json.JSONDecodeError as exc:
        raise gr.Error(f"Invalid JSON Schema: {exc.msg} at line {exc.lineno}") from exc
    if not isinstance(schema, dict):
        raise gr.Error("JSON Schema must be a JSON object.")
    return schema


def _validate_url(value: str | None) -> str:
    url = _s(value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise gr.Error("Seed URL must be a complete HTTP or HTTPS URL.")
    return url


def _s(value: str | None) -> str:
    return (value or "").strip()


def _build_request(
    seed_url: str,
    goal: str | None,
    extract_prompt: str | None,
    extract_schema: str | None,
    max_depth: float,
    max_pages: float,
    token_budget: float,
    same_domain: bool,
    include_patterns: str | None,
    exclude_patterns: str | None,
    date_filter: str | None,
    include_undated: bool,
    css_selector: str | None,
    max_chars: float,
) -> dict:
    return {
        "seed_url": seed_url,
        "goal": _s(goal),
        "extract_prompt": _s(extract_prompt),
        "extract_schema": _parse_schema(extract_schema),
        "max_depth": int(max_depth),
        "max_pages": int(max_pages),
        "token_budget": int(token_budget),
        "same_domain": same_domain,
        "include_patterns": _parse_patterns(include_patterns),
        "exclude_patterns": _parse_patterns(exclude_patterns),
        "date_filter": _s(date_filter),
        "include_undated": include_undated,
        "css_selector": _s(css_selector),
        "max_chars": int(max_chars),
    }


def _output_path(fmt: str) -> str:
    suffix = ".jsonl" if fmt == "jsonl" else ".json"
    return str(Path(tempfile.gettempdir()) / f"crawl-tool-{uuid4().hex}{suffix}")


async def run_crawl(
    seed_url: str | None,
    goal: str | None,
    extract_prompt: str | None,
    extract_schema: str | None,
    max_depth: float,
    max_pages: float,
    token_budget: float,
    same_domain: bool,
    include_patterns: str | None,
    exclude_patterns: str | None,
    date_filter: str | None,
    include_undated: bool,
    css_selector: str | None,
    max_chars: float,
    output_format: str,
) -> AsyncIterator[tuple]:
    """Drive a crawl over HTTP and yield progress and result components.

    Yields:
        Status, table HTML, payload state, JSON preview, extraction flag, and download path.
    """
    url = _validate_url(seed_url)
    request = _build_request(
        url,
        goal,
        extract_prompt,
        extract_schema,
        max_depth,
        max_pages,
        token_budget,
        same_domain,
        include_patterns,
        exclude_patterns,
        date_filter,
        include_undated,
        css_selector,
        max_chars,
    )
    extraction_requested = bool(_s(extract_prompt) or _s(extract_schema))
    hold = (gr.update(), gr.update(), gr.update(), gr.update(), gr.update())

    try:
        job_id = await start_crawl(request)
        status: dict = {}
        async for status in poll_until_done(job_id):
            if status["status"] == "running":
                collected = status.get("progress", {}).get("pages_collected", 0)
                yield (f"Running - {collected} page(s) collected...", *hold)
    except httpx.HTTPError as exc:
        yield (f"Engine error: {exc}", *hold)
        return

    if status.get("status") == "error":
        yield (f"Crawl failed: {status.get('error')}", *hold)
        return

    payload = status["payload"]
    table = build_result_table(payload, "Extracted", extraction_requested=extraction_requested)
    table_html = render_result_table_html(table)
    meta = payload["meta"]
    status_message = (
        f"Collected {meta['total_pages']} page(s), "
        f"{meta['successful']} successful, {meta['failed']} failed."
    )

    fmt = output_format.lower()
    try:
        data = await download_result(job_id, fmt)
    except httpx.HTTPError as exc:
        yield (f"Engine error: {exc}", *hold)
        return
    output_path = _output_path(fmt)
    await asyncio.to_thread(Path(output_path).write_bytes, data)

    yield (
        status_message,
        table_html,
        payload,
        payload,
        extraction_requested,
        output_path,
    )


def _sample_tags(samples: list[tuple[str, str]], target: gr.Textbox) -> None:
    """Render compact preset buttons that fill a textbox client-side."""
    with gr.Row(elem_classes="sample-strip"):
        for label, value in samples:
            btn = gr.Button(
                label,
                size="sm",
                min_width=0,
                elem_classes="sample-tag",
            )
            btn.click(None, outputs=target, js=f"() => {json.dumps(value)}")
