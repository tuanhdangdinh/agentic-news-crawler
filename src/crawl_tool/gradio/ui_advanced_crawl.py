"""Advanced crawl page — full form with all controls."""

from __future__ import annotations

import gradio as gr

from crawl_tool.gradio.ui_results import build_result_table, render_result_table_html
from crawl_tool.gradio.ui_shared import (
    _CSS_SELECTOR_SAMPLES,
    _DATE_FILTER_SAMPLES,
    _EXTRACT_PROMPT_SAMPLES,
    _GOAL_SAMPLES,
    _SEED_URL_SAMPLES,
    _sample_tags,
    run_crawl,
)


def build_advanced_crawl_page() -> gr.Column:
    """Build the advanced crawl form as a hideable column."""
    _init_table_html = render_result_table_html(
        build_result_table({}, "Extracted", extraction_requested=False)
    )

    with gr.Column(visible=False) as col:
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
                    info="Natural-language objective.",
                    lines=3,
                )
                _sample_tags(_GOAL_SAMPLES, goal)
                with gr.Row(equal_height=True):
                    date_filter = gr.Textbox(
                        label="Date filter",
                        placeholder="last 7 days",
                        info="Enforced publication-date range.",
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
                    placeholder="Extract the article title, publish date, author name, and key financial figures",
                    info="Fields to pull from each article. Leave blank to skip structured extraction.",
                    lines=3,
                )
                _sample_tags(_EXTRACT_PROMPT_SAMPLES, extract_prompt)
                with gr.Row(equal_height=True):
                    max_pages = gr.Slider(1, 100, value=4, step=1, label="Maximum pages", scale=2, min_width=180)
                    max_depth = gr.Slider(0, 5, value=1, step=1, label="Maximum depth", scale=2, min_width=180)
                output_format = gr.Radio(["JSON", "JSONL"], value="JSON", label="Download format")

        with gr.Accordion("Extraction schema", open=False):
            extract_schema = gr.Code(label="Optional JSON Schema", language="json", lines=10)
            gr.Markdown("_Paste a JSON Schema to enforce exact output shape._")

        with gr.Accordion("Crawl controls", open=False):
            with gr.Row():
                same_domain = gr.Checkbox(value=True, label="Stay on seed domain")
                css_selector = gr.Textbox(
                    label="CSS selector",
                    placeholder="article.main-content",
                    info="Scope page content to this element.",
                )
            _sample_tags(_CSS_SELECTOR_SAMPLES, css_selector)
            with gr.Row():
                max_chars = gr.Number(value=0, precision=0, label="Max markdown chars")
                token_budget = gr.Number(value=500_000, precision=0, label="Token budget")
            with gr.Row():
                include_patterns = gr.Textbox(label="Include URL patterns", lines=4)
                exclude_patterns = gr.Textbox(label="Exclude URL patterns", lines=4)

        run_button = gr.Button("Run crawl", variant="primary", elem_classes="run-button")
        status = gr.Markdown("")
        download = gr.File(label="Download result", visible=False)
        payload_state = gr.State({})
        extraction_state = gr.State(False)

        with gr.Tabs():
            with gr.TabItem("Extracted Data"):
                with gr.Row():
                    mode_radio = gr.Radio(["Extracted", "All pages"], value="Extracted", label="Show", scale=0)
                table_html = gr.HTML(value=_init_table_html)
            with gr.TabItem("Raw JSON"):
                json_preview = gr.JSON(label="Raw payload", value=None, open=True)

        inputs = [
            seed_url, goal, extract_prompt, extract_schema, max_depth, max_pages,
            token_budget, same_domain, include_patterns, exclude_patterns,
            date_filter, include_undated, css_selector, max_chars, output_format,
        ]
        run_button.click(
            fn=run_crawl,
            inputs=inputs,
            outputs=[status, table_html, payload_state, json_preview, extraction_state, download],
            concurrency_limit=1,
        )

        def on_mode_change(mode: str, payload: dict, extraction_requested: bool) -> str:
            table = build_result_table(payload, mode, extraction_requested=extraction_requested)
            return render_result_table_html(table)

        mode_radio.change(
            fn=on_mode_change,
            inputs=[mode_radio, payload_state, extraction_state],
            outputs=[table_html],
        )

    return col
