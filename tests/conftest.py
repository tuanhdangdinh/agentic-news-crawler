import os
import tempfile
from pathlib import Path

import certifi
import pytest
from crawl_tool.engine.logging_config import configure_logging

os.environ.setdefault(
    "CRAWL4_AI_BASE_DIRECTORY",
    str(Path(tempfile.gettempdir()) / "crawl-tool-pytest"),
)

# Point httpx (used by the Anthropic SDK) and requests to certifi's CA bundle.
# Needed on macOS with Anaconda Python where the system bundle may be incomplete.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


@pytest.fixture(autouse=True, scope="session")
def setup_logging() -> None:
    configure_logging(verbose=True)
