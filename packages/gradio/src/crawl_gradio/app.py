"""Launch the Crawl Tool Gradio interface."""

from crawl_engine.logging_config import configure_logging

from crawl_gradio.ui import _RESULT_JS, CUSTOM_CSS, build_demo


def main() -> None:
    """Configure logging and launch the web interface."""
    configure_logging(verbose=False)
    build_demo().queue(default_concurrency_limit=1).launch(css=CUSTOM_CSS, js=_RESULT_JS)


if __name__ == "__main__":
    main()
