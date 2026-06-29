"""Launch the Crawl Tool Gradio interface."""

from __future__ import annotations

import logging

import gradio as gr

from crawl_tool.gradio.ui_advanced_crawl import build_advanced_crawl_page
from crawl_tool.gradio.ui_quick_crawl import build_quick_crawl_page
from crawl_tool.gradio.ui_storage import build_storage_page
from crawl_tool.gradio.ui_styles import _RESULT_JS, CUSTOM_CSS

_NAV_PAGES = ["Quick Crawl", "Advanced Crawl", "Storage"]

_NAV_CSS = """
.nav-radio label { display: none !important; }
.nav-radio .wrap {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.nav-radio .wrap label.svelte-1ixch81 {
  display: flex !important;
  padding: 0.65rem 1rem;
  border-radius: 10px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  color: var(--crawler-muted);
  transition: all 0.15s ease;
}
.nav-radio .wrap label.svelte-1ixch81:hover {
  background: rgba(201, 79, 45, 0.06);
  color: var(--crawler-ink);
}
.nav-radio input:checked + label.svelte-1ixch81 {
  background: rgba(201, 79, 45, 0.1);
  color: var(--crawler-accent);
}
"""


def _switch_page(choice: str) -> list[dict]:
    return [gr.update(visible=(choice == page)) for page in _NAV_PAGES]


def build_demo() -> gr.Blocks:
    """Build the Gradio multi-page crawler interface."""
    with gr.Blocks(title="VSF Crawl Tool") as demo:
        with gr.Row():
            with gr.Column(scale=1, min_width=180):
                gr.HTML(
                    '<div style="padding: 1.5rem 1rem 1rem;">'
                    '<span style="font-weight: 900; font-size: 1.1rem; color: #18231f;">VSF Crawl Tool</span>'
                    "</div>"
                )
                nav = gr.Radio(
                    _NAV_PAGES,
                    value="Quick Crawl",
                    label="",
                    elem_classes="nav-radio",
                )

            with gr.Column(scale=4):
                quick_col = build_quick_crawl_page()
                advanced_col = build_advanced_crawl_page()
                storage_col = build_storage_page()

        nav.change(
            fn=_switch_page,
            inputs=[nav],
            outputs=[quick_col, advanced_col, storage_col],
        )

    return demo


def main() -> None:
    """Configure logging and launch the web interface."""
    logging.basicConfig(level=logging.INFO)
    build_demo().queue(default_concurrency_limit=1).launch(
        server_name="0.0.0.0",
        server_port=7860,
        css=CUSTOM_CSS + _NAV_CSS,
        js=_RESULT_JS,
    )


if __name__ == "__main__":
    main()
