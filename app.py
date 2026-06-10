"""Launch the Crawl Tool Gradio interface."""

from src.logging_config import configure_logging
from src.ui import CUSTOM_CSS, build_demo


def main() -> None:
    """Configure logging and launch the web interface."""
    configure_logging(verbose=False)
    build_demo().queue(default_concurrency_limit=1).launch(css=CUSTOM_CSS)


if __name__ == "__main__":
    main()
