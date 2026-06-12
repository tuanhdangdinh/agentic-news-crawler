"""Launch the Crawl Tool UI pre-loaded with a crawl result JSON file.

Usage:
    uv run dev_ui.py results-cafef.json
    uv run dev_ui.py /path/to/crawl-output.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from crawl_gradio.ui import _RESULT_JS, CUSTOM_CSS, build_demo

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
    """Launch the crawler UI with a result payload preloaded."""
    if len(sys.argv) < 2:
        print("Usage: uv run dev_ui.py <result.json>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    payload = json.loads(path.read_text())
    logging.basicConfig(level=logging.INFO)
    build_demo(initial_payload=payload).queue(default_concurrency_limit=1).launch(
        css=f"{CUSTOM_CSS}\n{DEV_UI_CSS}",
        head=DEV_UI_HEAD,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
