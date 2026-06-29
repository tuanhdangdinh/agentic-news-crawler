"""Quick crawl page — one-prompt NL flow with parse-then-edit."""

from __future__ import annotations

import gradio as gr
import httpx

from crawl_tool.gradio.client import parse_prompt
from crawl_tool.gradio.ui_results import build_result_table, render_result_table_html
from crawl_tool.gradio.ui_shared import (
    _EXTRACT_PROMPT_SAMPLES,
    _sample_tags,
    run_crawl,
)

_PROMPT_SAMPLES = [
    (
        "Finance CafeF 7d",
        "Get finance and banking news from https://cafef.vn for the last 7 days, "
        "extract title, author, and one-sentence summary",
    ),
    (
        "Stock VnEconomy",
        "Collect the 20 most recent stock market articles from https://vneconomy.vn, "
        "extract title, publish date, and tickers mentioned",
    ),
    (
        "USD/VND VietnamPlus",
        "Find articles about USD/VND exchange rate on https://en.vietnamplus.vn "
        "from the last 30 days",
    ),
]

_INFERRED_FIELDS = ["seed_url", "goal", "date_filter", "extract_prompt", "max_depth", "max_pages"]
_FIELD_DEFAULTS: dict[str, object] = {
    "seed_url": "",
    "goal": "",
    "date_filter": "",
    "extract_prompt": "",
    "max_depth": 1,
    "max_pages": 10,
}


def _populate_fields(parsed: dict) -> tuple:
    """Return gr.update values for all Phase 2 inputs from the parsed dict.

    Args:
        parsed: Dict with any subset of _INFERRED_FIELDS as keys.

    Returns:
        Tuple of 6 gr.update dicts in field order: seed_url, goal, date_filter,
        extract_prompt, max_depth, max_pages.
    """
    return tuple(
        gr.update(value=parsed.get(field, _FIELD_DEFAULTS[field]))
        for field in _INFERRED_FIELDS
    )


def _inferred_chip_html(parsed: dict) -> str:
    """Render chip strip showing which fields were inferred vs. left at defaults.

    Args:
        parsed: Dict with the fields that were inferred from the NL prompt.

    Returns:
        HTML string with one chip per field; inferred fields show "✓",
        missing fields show "— default".
    """
    chips = []
    for field in _INFERRED_FIELDS:
        if field in parsed:
            chips.append(f'<span class="chip">{field} ✓</span>')
        else:
            chips.append(f'<span class="chip" style="opacity:0.4">{field} — default</span>')
    return f'<div class="chip-list">{"".join(chips)}</div>'


def build_quick_crawl_page() -> gr.Column:
    """Build the quick crawl page as a hideable column."""
    _init_table_html = render_result_table_html(
        build_result_table({}, "Extracted", extraction_requested=False)
    )

    with gr.Column(visible=True) as col:
        # ── Phase 1: prompt input ────────────────────────────────────────
        with gr.Column(visible=True) as phase1_col:
            gr.Markdown("### Describe your crawl")
            gr.Markdown(
                "Include the site URL, what you want to collect, any date range, "
                "and what fields to extract."
            )
            prompt_input = gr.Textbox(
                label="Crawl prompt",
                placeholder=(
                    "Get finance and banking news from https://cafef.vn "
                    "for the last 7 days, extract title, author, and one-sentence summary"
                ),
                lines=5,
            )
            _sample_tags(_PROMPT_SAMPLES, prompt_input)
            parse_error = gr.Markdown("", visible=False)
            parse_btn = gr.Button("Parse →", variant="primary", elem_classes="run-button")

        # ── Phase 2: editable preview + run ─────────────────────────────
        with gr.Column(visible=False) as phase2_col:
            edit_link = gr.Button("← Edit prompt", size="sm")
            inferred_chips = gr.HTML("")

            seed_url_field = gr.Textbox(label="Seed URL")
            goal_field = gr.Textbox(label="Crawl goal", lines=2)
            date_filter_field = gr.Textbox(label="Date filter", placeholder="last 7 days")
            extract_prompt_field = gr.Textbox(label="Extraction prompt", lines=2)
            _sample_tags(_EXTRACT_PROMPT_SAMPLES, extract_prompt_field)
            with gr.Row():
                max_depth_field = gr.Slider(0, 5, value=1, step=1, label="Max depth", scale=1)
                max_pages_field = gr.Slider(1, 100, value=10, step=1, label="Max pages", scale=1)

            run_btn = gr.Button("Run crawl", variant="primary", elem_classes="run-button")

        # ── Results ──────────────────────────────────────────────────────
        run_status = gr.Markdown("")
        run_download = gr.File(label="Download result", visible=False)
        payload_state = gr.State({})
        extraction_state = gr.State(False)

        with gr.Tabs():
            with gr.TabItem("Extracted Data"):
                table_html = gr.HTML(value=_init_table_html)
            with gr.TabItem("Raw JSON"):
                json_preview = gr.JSON(label="Raw payload", value=None, open=True)

        # ── Event handlers ───────────────────────────────────────────────
        async def _on_parse(prompt: str):
            if not prompt.strip():
                yield (
                    gr.update(visible=True),   # phase1
                    gr.update(visible=False),  # phase2
                    gr.update(value="Enter a prompt first.", visible=True),  # error
                    *(_populate_fields({})),
                    gr.update(value=""),  # chips
                )
                return
            try:
                parsed = await parse_prompt(prompt)
            except httpx.HTTPStatusError as exc:
                msg = exc.response.json().get("detail", str(exc))
                yield (
                    gr.update(visible=True),
                    gr.update(visible=False),
                    gr.update(value=f"**Parse error:** {msg}", visible=True),
                    *(_populate_fields({})),
                    gr.update(value=""),
                )
                return
            except httpx.RequestError as exc:
                yield (
                    gr.update(visible=True),
                    gr.update(visible=False),
                    gr.update(value=f"**Engine unreachable:** {exc}", visible=True),
                    *(_populate_fields({})),
                    gr.update(value=""),
                )
                return
            yield (
                gr.update(visible=False),   # hide phase1
                gr.update(visible=True),    # show phase2
                gr.update(value="", visible=False),  # clear error
                *(_populate_fields(parsed)),
                gr.update(value=_inferred_chip_html(parsed)),
            )

        parse_btn.click(
            fn=_on_parse,
            inputs=[prompt_input],
            outputs=[
                phase1_col,
                phase2_col,
                parse_error,
                seed_url_field,
                goal_field,
                date_filter_field,
                extract_prompt_field,
                max_depth_field,
                max_pages_field,
                inferred_chips,
            ],
        )

        def _on_edit():
            return gr.update(visible=True), gr.update(visible=False)

        edit_link.click(fn=_on_edit, outputs=[phase1_col, phase2_col])

        async def _run_quick(
            seed_url: str,
            goal: str,
            extract_prompt: str,
            date_filter: str,
            max_depth: float,
            max_pages: float,
        ):
            async for frame in run_crawl(
                seed_url,
                goal,
                extract_prompt,
                None,
                max_depth,
                max_pages,
                500_000,
                True,
                None,
                None,
                date_filter,
                True,
                None,
                0,
                "JSON",
            ):
                yield frame

        run_btn.click(
            fn=_run_quick,
            inputs=[
                seed_url_field,
                goal_field,
                extract_prompt_field,
                date_filter_field,
                max_depth_field,
                max_pages_field,
            ],
            outputs=[
                run_status,
                table_html,
                payload_state,
                json_preview,
                extraction_state,
                run_download,
            ],
            concurrency_limit=1,
        )

    return col
