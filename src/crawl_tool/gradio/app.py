"""Launch the Crawl Tool Gradio interface."""

import logging

from crawl_tool.gradio.ui import _RESULT_JS, CUSTOM_CSS, build_demo


def main() -> None:
    """Configure logging and launch the web interface."""
    logging.basicConfig(level=logging.INFO)
    build_demo().queue(default_concurrency_limit=1).launch(
        server_name="0.0.0.0",
        server_port=7860,
        css=CUSTOM_CSS,
        js=_RESULT_JS,
    )


if __name__ == "__main__":
    main()
