"""Gradio interface for configuring and running crawls."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import gradio as gr

from src.agent import AgentConfig, CrawlState, run_agent
from src.crawler import fetch_page
from src.models import PageResult
from src.output import write_results

CUSTOM_CSS = """
:root {
  --crawler-ink: #18231f;
  --crawler-muted: #627069;
  --crawler-accent: #c94f2d;
}
.gradio-container {
  max-width: 1180px !important;
}
.hero {
  padding: 1.4rem 0 0.6rem;
}
.hero h1 {
  color: var(--crawler-ink);
  font-size: clamp(2rem, 5vw, 3.8rem);
  letter-spacing: -0.055em;
  line-height: 0.95;
  margin: 0;
}
.hero p {
  color: var(--crawler-muted);
  font-size: 1.05rem;
  max-width: 720px;
}
.run-button {
  background: var(--crawler-accent) !important;
  border-color: var(--crawler-accent) !important;
}
.primary-panel {
  border: 1px solid rgba(24, 35, 31, 0.07) !important;
  border-radius: 1rem !important;
  background: rgba(255, 255, 255, 0.58) !important;
  padding: 0.85rem !important;
}
.primary-panel-title {
  color: var(--crawler-ink);
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  margin: 0 0 0.15rem;
  text-transform: uppercase;
}
/* Minimal preset picker shown below supported fields. */
.sample-strip {
  gap: 0.5rem !important;
  flex-wrap: wrap !important;
  align-items: flex-start !important;
  margin: -0.12rem 0 0.82rem !important;
  border: 1px solid rgba(24, 35, 31, 0.07) !important;
  border-radius: 0.75rem !important;
  background:
    linear-gradient(135deg, rgba(255, 232, 223, 0.98), rgba(255, 255, 255, 0.92))
    !important;
  padding: 0.42rem 0.55rem !important;
  min-height: 0 !important;
  box-shadow: 0 1px 2px rgba(24, 35, 31, 0.04) !important;
}
.sample-strip > div {
  flex: none !important;
}
.sample-tag {
  background: #fff !important;
  border: 1px solid rgba(24, 35, 31, 0.1) !important;
  color: var(--crawler-ink) !important;
  border-radius: 999px !important;
  padding: 0.25rem 0.62rem !important;
  font-size: 0.7rem !important;
  font-weight: 600 !important;
  line-height: 1.1 !important;
  cursor: pointer !important;
  min-width: unset !important;
  height: auto !important;
  box-shadow: none !important;
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s,
    transform 0.15s;
}
.sample-tag:hover {
  background: rgba(201, 79, 45, 0.06) !important;
  border-color: rgba(201, 79, 45, 0.3) !important;
  color: var(--crawler-accent) !important;
  transform: translateY(-1px);
}
.sample-tag:focus-visible {
  outline: 2px solid var(--crawler-accent) !important;
  outline-offset: 2px !important;
}
@media (max-width: 640px) {
  .sample-strip {
    gap: 0.34rem !important;
    padding: 0.38rem 0.46rem !important;
  }
}
"""

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


def _build_config(
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
) -> AgentConfig:
    return AgentConfig(
        goal=_s(goal),
        extract_prompt=_s(extract_prompt),
        extract_schema=_parse_schema(extract_schema),
        max_depth=int(max_depth),
        max_pages=int(max_pages),
        token_budget=int(token_budget),
        same_domain=same_domain,
        include_patterns=_parse_patterns(include_patterns),
        exclude_patterns=_parse_patterns(exclude_patterns),
        date_filter=_s(date_filter),
        include_undated=include_undated,
        css_selector=_s(css_selector),
        max_chars=int(max_chars),
    )


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
        "article_pages": state.article_pages,
        "urls_visited": len(state.visited),
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "finish_reason": state.finish_reason,
        "stop_reason": state.stop_reason,
        "frontier_at_finish": state.frontier_at_finish,
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
) -> tuple[str, dict, str]:
    """Run a configured crawl and return status, preview, and download path.

    Args:
        seed_url: Initial URL to fetch.
        goal: Natural-language crawl objective.
        extract_prompt: Structured extraction request.
        extract_schema: Optional JSON Schema text.
        max_depth: Maximum link depth.
        max_pages: Maximum number of fetched pages.
        token_budget: Maximum Claude token usage.
        same_domain: Whether links must remain on the seed domain.
        include_patterns: Newline-separated URL inclusion patterns.
        exclude_patterns: Newline-separated URL exclusion patterns.
        date_filter: Natural-language publication-date range.
        include_undated: Whether pages without dates are eligible.
        css_selector: Optional content-scoping selector.
        max_chars: Maximum markdown characters sent to Claude.
        output_format: Download format, either JSON or JSONL.

    Returns:
        Human-readable status, JSON preview, and generated output path.
    """
    url = _validate_url(seed_url)
    config = _build_config(
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

    if not config.goal and not config.extract_prompt:
        page = await fetch_page(url, css_selector=config.css_selector or None)
        pages = [page]
        run_meta = _direct_run_meta(url, page)
    else:
        state = await run_agent(url, config)
        pages = state.pages
        run_meta = _agent_run_meta(url, config, state)

    fmt = output_format.lower()
    output_path = _output_path(fmt)
    write_results(pages, output_path, fmt=fmt, run_meta=run_meta)
    payload = _result_payload(pages, run_meta)
    status = (
        f"Collected {len(pages)} page(s), "
        f"{payload['meta']['successful']} successful, "
        f"{payload['meta']['failed']} failed."
    )
    return status, payload, output_path


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


def build_demo() -> gr.Blocks:
    """Build the Gradio crawler interface.

    Returns:
        Configured Gradio Blocks application.
    """
    with gr.Blocks(title="VSF Crawl Tool") as demo:
        gr.HTML(
            """
            <section class="hero">
              <h1>VSF Crawl Tool</h1>
              <p>Point the agent at any site, describe what you need, and download
              clean structured data — no code required.</p>
            </section>
            """
        )

        seed_url = gr.Textbox(
            label="Seed URL",
            placeholder="https://cafef.vn/ngan-hang.chn",
            info="Starting URL the agent crawls from. Must be a full HTTP or HTTPS address.",
        )
        _sample_tags(_SEED_URL_SAMPLES, seed_url)

        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=360, elem_classes="primary-panel"):
                gr.HTML('<p class="primary-panel-title">What to crawl</p>')
                goal = gr.Textbox(
                    label="Crawl goal",
                    placeholder="Collect the 20 most recent banking and stock market articles",
                    info="Natural-language objective. The agent follows links and decides what to fetch based on this.",
                    lines=3,
                )
                _sample_tags(_GOAL_SAMPLES, goal)

                with gr.Row(equal_height=True):
                    date_filter = gr.Textbox(
                        label="Date filter",
                        placeholder="last 7 days",
                        info="An enforced publication-date range, separate from the crawl goal.",
                        scale=3,
                        min_width=240,
                    )
                    include_undated = gr.Checkbox(
                        value=True,
                        label="Include undated",
                        info="Keep pages whose publish date cannot be detected.",
                        scale=1,
                        min_width=130,
                    )
                _sample_tags(_DATE_FILTER_SAMPLES, date_filter)

            with gr.Column(scale=1, min_width=360, elem_classes="primary-panel"):
                gr.HTML('<p class="primary-panel-title">What to return</p>')
                extract_prompt = gr.Textbox(
                    label="Extraction prompt",
                    placeholder=(
                        "Extract the article title, publish date, author name, "
                        "stock tickers mentioned, and key financial figures"
                    ),
                    info="Fields to pull from each article. Leave blank to skip structured extraction and return raw pages.",
                    lines=3,
                )
                _sample_tags(_EXTRACT_PROMPT_SAMPLES, extract_prompt)

                with gr.Row(equal_height=True):
                    max_pages = gr.Slider(
                        1,
                        100,
                        value=4,
                        step=1,
                        label="Maximum pages",
                        info="Hard cap on fetched pages.",
                        scale=2,
                        min_width=180,
                    )
                    max_depth = gr.Slider(
                        0,
                        5,
                        value=1,
                        step=1,
                        label="Maximum depth",
                        info="Allowed link hops from the seed.",
                        scale=2,
                        min_width=180,
                    )
                output_format = gr.Radio(
                    ["JSON", "JSONL"],
                    value="JSON",
                    label="Download format",
                    info="JSON wraps the run; JSONL writes one page per line.",
                )

        with gr.Accordion("Extraction schema", open=False):
            extract_schema = gr.Code(
                label="Optional JSON Schema",
                language="json",
                lines=10,
            )
            gr.Markdown(
                "_Paste a JSON Schema to enforce exact output shape. "
                "Leave empty to let the agent infer a schema from the extraction prompt._"
            )

        with gr.Accordion("Crawl controls", open=False):
            with gr.Row():
                same_domain = gr.Checkbox(
                    value=True,
                    label="Stay on seed domain",
                    info="When checked, links that leave the seed domain are ignored.",
                )
                css_selector = gr.Textbox(
                    label="CSS selector",
                    placeholder="article.main-content",
                    info="Scope page content to this element before extraction. Reduces noise from navbars and footers.",
                )
            _sample_tags(_CSS_SELECTOR_SAMPLES, css_selector)

            with gr.Row():
                max_chars = gr.Number(
                    value=0,
                    precision=0,
                    label="Max markdown chars",
                    info="Truncate content sent to Claude. 0 means no limit. Set to e.g. 8000 to cap token use on long pages.",
                )
                token_budget = gr.Number(
                    value=500_000,
                    precision=0,
                    label="Token budget",
                    info="Maximum Claude tokens the agent may consume.",
                )

            with gr.Row():
                include_patterns = gr.Textbox(
                    label="Include URL patterns",
                    placeholder="**/tin-tuc/**\n**/chung-khoan/**",
                    info="One glob pattern per line. Only URLs matching at least one pattern are followed.",
                    lines=4,
                )
                exclude_patterns = gr.Textbox(
                    label="Exclude URL patterns",
                    placeholder="**/tag/**\n**/search/**",
                    info="One glob pattern per line. URLs matching any pattern are skipped.",
                    lines=4,
                )

        run_button = gr.Button("Run crawl", variant="primary", elem_classes="run-button")

        with gr.Row():
            status = gr.Markdown("Ready.")
            download = gr.File(label="Download result", interactive=False)
        preview = gr.JSON(label="Result preview", open=True)

        inputs = [
            seed_url,
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
            output_format,
        ]
        run_button.click(
            fn=run_crawl,
            inputs=inputs,
            outputs=[status, preview, download],
            concurrency_limit=1,
        )

    return demo
