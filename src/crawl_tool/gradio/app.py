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
.nav-rail {
  border-right: 1px solid #e5e7eb;
  min-height: 80vh;
  padding: 0 0.75rem 0 0;
}
.nav-btn button {
  width: 100%;
  justify-content: flex-start;
  text-align: left;
  border: none !important;
  border-radius: 10px !important;
  font-weight: 600;
  font-size: 0.9rem;
  padding: 0.65rem 1rem;
  background: transparent !important;
  color: #6b7280 !important;
  box-shadow: none !important;
  transition: background 0.15s ease, color 0.15s ease;
}
.nav-btn button:hover {
  background: rgba(201, 79, 45, 0.06) !important;
  color: #18231f !important;
}
.nav-btn-active button {
  background: rgba(201, 79, 45, 0.12) !important;
  color: #c94f2d !important;
}
"""


def _nav_updates(active: str) -> list:
    """Return (page_visibility × 3, button_classes × 3) updates."""
    page_updates = [gr.update(visible=(active == p)) for p in _NAV_PAGES]
    btn_updates = [
        gr.update(elem_classes="nav-btn nav-btn-active" if active == p else "nav-btn")
        for p in _NAV_PAGES
    ]
    return page_updates + btn_updates


def build_demo() -> gr.Blocks:
    """Build the Gradio multi-page crawler interface."""
    with gr.Blocks(title="VSF Crawl Tool") as demo:
        with gr.Row():
            # ── Sidebar ──────────────────────────────────────────────────
            with gr.Column(scale=1, min_width=200, elem_classes="nav-rail"):
                gr.HTML(
                    '<div style="padding: 1.5rem 0.5rem 1rem;">'
                    '<span style="font-weight: 900; font-size: 1.1rem; color: #18231f;">'
                    "VSF Crawl Tool"
                    "</span></div>"
                )
                btn_quick = gr.Button(
                    "Quick Crawl", elem_classes="nav-btn nav-btn-active", size="sm"
                )
                btn_advanced = gr.Button(
                    "Advanced Crawl", elem_classes="nav-btn", size="sm"
                )
                btn_storage = gr.Button(
                    "Storage", elem_classes="nav-btn", size="sm"
                )

            # ── Content area ─────────────────────────────────────────────
            with gr.Column(scale=4):
                quick_col = build_quick_crawl_page()
                advanced_col = build_advanced_crawl_page()
                storage_col, _storage_load, _storage_stats_html, _storage_objects_table = (
                    build_storage_page()
                )

        _page_outputs = [quick_col, advanced_col, storage_col]
        _btn_outputs = [btn_quick, btn_advanced, btn_storage]

        btn_quick.click(
            fn=lambda: _nav_updates("Quick Crawl"),
            outputs=_page_outputs + _btn_outputs,
        )
        btn_advanced.click(
            fn=lambda: _nav_updates("Advanced Crawl"),
            outputs=_page_outputs + _btn_outputs,
        )
        btn_storage.click(
            fn=lambda: _nav_updates("Storage"),
            outputs=_page_outputs + _btn_outputs,
        )
        demo.load(fn=_storage_load, outputs=[_storage_stats_html, _storage_objects_table])

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
