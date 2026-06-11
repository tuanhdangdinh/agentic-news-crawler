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
from src.ui_results import (
    build_result_table,
    render_result_table_html,
)

# Runs once on page load; defines selection and filtering for the split result view.
_RESULT_JS = """
() => {
  window.rtSelect = function(row, id) {
    const wrap = row.closest('.rt-split-wrap');
    if (!wrap) return;

    // Clear previous selection
    wrap.querySelectorAll('.rt-row-selected').forEach(r => r.classList.remove('rt-row-selected'));
    wrap.querySelectorAll('.rt-det-active').forEach(d => d.classList.remove('rt-det-active'));

    // Set new selection
    row.classList.add('rt-row-selected');
    const det = document.getElementById(id);
    if (det) {
      det.classList.add('rt-det-active');
      // Scroll detail panel to top when switching
      det.closest('.rt-detail-content').scrollTop = 0;
    }
  };

  window.rtFilter = function(input) {
    const q = input.value.toLowerCase().trim();
    const wrap = input.closest('.rt-split-wrap');
    if (!wrap) return;

    let visible = 0;
    let firstMatch = null;

    wrap.querySelectorAll('.rt-row').forEach(row => {
      const match = !q || (row.dataset.search || '').includes(q);
      row.style.display = match ? '' : 'none';
      if (match) {
        visible++;
        if (!firstMatch) firstMatch = row;
      }
    });

    const countEl = wrap.querySelector('.rt-count');
    if (countEl) countEl.textContent = visible + (visible === 1 ? ' result' : ' results');

    // If current selection is hidden, select the first visible match
    const selected = wrap.querySelector('.rt-row-selected');
    if (selected && selected.style.display === 'none' && firstMatch) {
      rtSelect(firstMatch, firstMatch.dataset.det);
    }
  };

  window.rtToggleFigure = function(button) {
    const target = document.getElementById(button.getAttribute('aria-controls'));
    if (!target) return;
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    target.hidden = expanded;
  };

  window.rtShowFigures = function(button) {
    const target = document.getElementById(button.getAttribute('aria-controls'));
    if (!target) return;
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    target.hidden = expanded;
    const collapsedLabel = button.dataset.collapsedLabel;
    const expandedLabel = button.dataset.expandedLabel;
    button.textContent = expanded ? collapsedLabel : expandedLabel;
  };
}
"""

CUSTOM_CSS = """
:root {
  --crawler-ink: #18231f;
  --crawler-muted: #627069;
  --crawler-accent: #c94f2d;
  --crawler-bg-soft: #fbfbfa;
  --crawler-border: rgba(24, 35, 31, 0.08);
  --crawler-radius: 16px;
  --crawler-shadow: 0 10px 30px rgba(24, 35, 31, 0.05);
}
.gradio-container {
  max-width: 1280px !important;
  background-color: #f8faf9 !important;
}
.hero {
  padding: 2.5rem 0 1.5rem;
}
.hero h1 {
  color: var(--crawler-ink);
  font-size: clamp(2.2rem, 6vw, 4.2rem);
  letter-spacing: -0.06em;
  line-height: 0.92;
  margin: 0;
}
.hero p {
  color: var(--crawler-muted);
  font-size: 1.15rem;
  max-width: 760px;
  margin-top: 0.75rem;
}
.run-button {
  background: var(--crawler-accent) !important;
  border-color: var(--crawler-accent) !important;
  box-shadow: 0 4px 14px rgba(201, 79, 45, 0.25) !important;
}
.primary-panel {
  border: 1px solid var(--crawler-border) !important;
  border-radius: var(--crawler-radius) !important;
  background: white !important;
  padding: 1.25rem !important;
  box-shadow: var(--crawler-shadow) !important;
}
.primary-panel-title {
  color: var(--crawler-ink);
  font-size: 0.85rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  margin: 0 0 0.25rem;
  text-transform: uppercase;
}
/* Minimal preset picker shown below supported fields. */
.sample-strip {
  gap: 0.5rem !important;
  flex-wrap: wrap !important;
  align-items: flex-start !important;
  margin: -0.12rem 0 0.82rem !important;
  padding: 0 !important;
  min-height: 0 !important;
}
.sample-tag {
  background: white !important;
  border: 1px solid var(--crawler-border) !important;
  color: var(--crawler-muted) !important;
  border-radius: 999px !important;
  padding: 0.35rem 0.75rem !important;
  font-size: 0.72rem !important;
  font-weight: 600 !important;
  line-height: 1 !important;
  cursor: pointer !important;
  min-width: unset !important;
  height: auto !important;
  transition: all 0.2s ease;
}
.sample-tag:hover {
  border-color: var(--crawler-accent) !important;
  color: var(--crawler-accent) !important;
  background: rgba(201, 79, 45, 0.03) !important;
  transform: translateY(-1px);
}
/* ── Shared badges / chips ───────────────────────────── */
.status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.35rem 0.85rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.status-ok  { background: #e9f6ef; color: #166534; }
.status-warn{ background: #fef9c3; color: #854d0e; }
.status-err { background: #fee2e2; color: #991b1b; }

.chip-list { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.chip {
  background: #f2f4f3;
  border-radius: 8px;
  padding: 0.3rem 0.7rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #4e5b55;
}
.kv-block { display: flex; flex-direction: column; gap: 0.5rem; }
.kv-row { 
  display: flex;
  background: #f7f8f7;
  padding: 0.5rem 0.8rem;
  border-radius: 8px;
}
.kv-key { 
  font-weight: 800; 
  color: var(--crawler-muted); 
  width: 110px;
  flex-shrink: 0;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.error-text { color: #991b1b; font-size: 0.85rem; background: #fee2e2; padding: 0.75rem; border-radius: 8px;}
.missing { color: var(--crawler-muted); font-style: italic; opacity: 0.5; }

/* ── Split result view ──────────────────────────────── */
.rt-empty {
  padding: 5rem;
  color: var(--crawler-muted);
  text-align: center;
  background: white;
  border-radius: var(--crawler-radius);
  border: 1px dashed var(--crawler-border);
}
.rt-split-wrap { 
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.6fr);
  gap: 1.5rem;
  background: var(--crawler-bg-soft);
  border: 1px solid var(--crawler-border);
  border-radius: 20px;
  padding: 1.25rem;
  box-shadow: var(--crawler-shadow);
  height: 720px;
}
@media (max-width: 1024px) {
  .rt-split-wrap { grid-template-columns: 1fr; height: auto; }
}
.rt-master {
  display: flex;
  flex-direction: column;
  background: white;
  border: 1px solid var(--crawler-border);
  border-radius: 16px;
  overflow: hidden;
}
.rt-toolbar {
  display: flex;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--crawler-border);
  gap: 1rem;
}
.rt-search {
  flex: 1;
  border: 1px solid var(--crawler-border);
  border-radius: 10px;
  padding: 0.65rem 1rem;
  font-size: 0.9rem;
}
.rt-search:focus {
  outline: none;
  border-color: var(--crawler-accent);
  box-shadow: 0 0 0 3px rgba(201, 79, 45, 0.1);
}
.rt-count {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--crawler-muted);
  background: #f2f4f3;
  padding: 0.4rem 0.8rem;
  border-radius: 99px;
}
.rt-table-scroll {
  flex: 1;
  overflow: auto;
}
.rt {
  width: 100%;
  border-collapse: collapse;
}
.rt th {
  position: sticky;
  top: 0;
  background: #f2f4f3;
  color: #59645f;
  text-align: left;
  padding: 0.85rem 1rem;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  z-index: 10;
}
.rt-row {
  cursor: pointer;
  border-bottom: 1px solid #f2f4f3;
  transition: all 0.2s ease;
}
.rt-row:hover { background: #fbfbfa; }
.rt-row-selected {
  background: #fff7f4 !important;
  box-shadow: inset 3px 0 var(--crawler-accent);
}
.rt-cell {
  padding: 1.15rem 1rem;
  font-size: 0.85rem;
  font-weight: 500;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rt-row-selected .rt-cell {
  font-weight: 600;
  color: var(--crawler-ink);
}

/* Detail Pane */
.rt-detail-pane {
  display: flex;
  flex-direction: column;
  background: white;
  border: 1px solid var(--crawler-border);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0,0,0,0.02);
}
.rt-detail-header {
  padding: 1rem 1.25rem;
  background: #fbfbfa;
  border-bottom: 1px solid var(--crawler-border);
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--crawler-muted);
}
.rt-detail-content {
  flex: 1;
  overflow-y: auto;
  position: relative;
}
.rt-det-item { display: none; padding: 1.5rem; }
.rt-det-active { display: block; animation: fadeIn 0.2s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

/* Re-use result-detail styles from before but refined */
.result-detail-header { margin-bottom: 2rem; }
.result-detail-fields dt {
  font-weight: 800;
  color: var(--crawler-muted);
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-top: 0.5rem;
}
.result-detail-fields dd {
  margin: 0.25rem 0 1rem;
  line-height: 1.6;
}
.result-detail-fields dd a { color: var(--crawler-accent); text-decoration: none; font-weight: 600; }
.result-detail-fields dd a:hover { text-decoration: underline; }

.figures-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  border: 1px solid #f2f4f3;
  border-radius: 8px;
  overflow: hidden;
}
.figures-table th { background: #fbfbfa; padding: 0.6rem 0.8rem; text-align: left; color: var(--crawler-muted); border-bottom: 1px solid #f2f4f3; }
.figures-table td { padding: 0.6rem 0.8rem; border-bottom: 1px solid #f2f4f3; }
.figures-more { background: #fbfbfa; color: var(--crawler-muted); text-align: center; font-size: 0.75rem; padding: 0.5rem; font-style: italic; }

.financial-ledger {
  border: 1px solid var(--crawler-border);
  border-radius: 10px;
  overflow: hidden;
}
.financial-figure {
  border-bottom: 1px solid var(--crawler-border);
}
.financial-figure:last-child {
  border-bottom: 0;
}
.financial-figure-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem 0.85rem;
}
.financial-figure-label {
  color: var(--crawler-ink);
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.35;
}
.financial-figure-meta {
  color: var(--crawler-muted);
  font-size: 0.7rem;
  margin-top: 0.2rem;
}
.financial-figure-value {
  color: var(--crawler-accent);
  font-size: 0.82rem;
  font-weight: 800;
  text-align: right;
}
.financial-figure-toggle,
.financial-figure-more {
  border: 1px solid var(--crawler-border);
  background: var(--crawler-bg-soft);
  color: var(--crawler-muted);
  cursor: pointer;
}
.financial-figure-toggle {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 6px;
  transition: transform 0.15s ease;
}
.financial-figure-toggle[aria-expanded="true"] {
  transform: rotate(180deg);
}
.financial-figure-toggle:focus-visible,
.financial-figure-more:focus-visible {
  outline: 2px solid var(--crawler-accent);
  outline-offset: 2px;
}
.financial-figure-context {
  padding: 0.65rem 0.85rem;
  border-left: 2px solid var(--crawler-accent);
  background: rgba(201, 79, 45, 0.06);
  color: var(--crawler-muted);
  font-size: 0.75rem;
  line-height: 1.5;
}
.financial-figure-more {
  width: 100%;
  padding: 0.6rem;
  border-width: 1px 0 0;
  font-size: 0.75rem;
  font-weight: 700;
}
@media (max-width: 640px) {
  .financial-figure-main {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .financial-figure-toggle {
    grid-column: 2;
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
) -> tuple[str, str, dict, dict, bool, str]:
    """Run a configured crawl and return result components.

    Returns:
        status, accordion table html, payload (for state),
        payload (for json preview), extraction_requested, download path.
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

    extraction_requested = bool(config.extract_prompt or config.extract_schema)
    table = build_result_table(payload, "Extracted", extraction_requested=extraction_requested)
    table_html = render_result_table_html(table)

    status = (
        f"Collected {len(pages)} page(s), "
        f"{payload['meta']['successful']} successful, "
        f"{payload['meta']['failed']} failed."
    )
    return status, table_html, payload, payload, extraction_requested, output_path


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


def build_demo(initial_payload: dict | None = None) -> gr.Blocks:
    """Build the Gradio crawler interface.

    Args:
        initial_payload: Pre-load the result view with this crawl payload on startup.
            Accepts the same dict shape written by write_results / run_crawl. When
            provided the accordion table and Raw JSON tab are populated immediately
            without running a crawl — useful for UI development.

    Returns:
        Configured Gradio Blocks application.
    """
    _init_payload = initial_payload or {}
    _init_extraction = any(
        (p.get("metadata") or {}).get("extracted") for p in _init_payload.get("pages", [])
    )
    _init_table_html = render_result_table_html(
        build_result_table(_init_payload, "Extracted", extraction_requested=_init_extraction)
    )

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

        # State: payload and extraction flag drive mode-change re-renders.
        payload_state = gr.State(_init_payload)
        extraction_state = gr.State(_init_extraction)

        with gr.Tabs():
            with gr.TabItem("Extracted Data"):
                with gr.Row():
                    mode_radio = gr.Radio(
                        ["Extracted", "All pages"],
                        value="Extracted",
                        label="Show",
                        scale=0,
                    )
                table_html = gr.HTML(value=_init_table_html)

            with gr.TabItem("Raw JSON"):
                json_preview = gr.JSON(label="Raw payload", value=_init_payload or None, open=True)

        def on_mode_change(mode: str, payload: dict, extraction_requested: bool) -> str:
            table = build_result_table(payload, mode, extraction_requested=extraction_requested)
            return render_result_table_html(table)

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
            outputs=[status, table_html, payload_state, json_preview, extraction_state, download],
            concurrency_limit=1,
        )
        mode_radio.change(
            fn=on_mode_change,
            inputs=[mode_radio, payload_state, extraction_state],
            outputs=[table_html],
        )

    return demo
