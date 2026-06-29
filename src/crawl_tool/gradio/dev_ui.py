"""Launch the Crawl Tool UI for development.

Usage:
    uv run dev_ui.py
"""

from __future__ import annotations

import logging

from crawl_tool.gradio.app import _NAV_CSS, build_demo
from crawl_tool.gradio.ui_styles import _RESULT_JS, CUSTOM_CSS

DEV_UI_CSS = """
.rt-row {
  cursor: pointer;
}
.rt-row:hover {
  background: rgba(201, 79, 45, 0.06);
}
.rt-row:focus-visible {
  outline: 2px solid #c94f2d;
  outline-offset: -2px;
}
.rt-row-selected {
  background: rgba(201, 79, 45, 0.1) !important;
  outline: 2px solid #c94f2d;
  outline-offset: -2px;
}
"""

DEV_UI_HEAD = f"<script>({_RESULT_JS})();</script>"


def main() -> None:
    """Launch the crawler UI for development."""
    logging.basicConfig(level=logging.INFO)
    build_demo().queue(default_concurrency_limit=1).launch(
        css=f"{CUSTOM_CSS}\n{_NAV_CSS}\n{DEV_UI_CSS}",
        head=DEV_UI_HEAD,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
