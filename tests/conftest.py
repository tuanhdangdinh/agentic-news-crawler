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


_PROXY_ENV_VARS = (
    "PROXY_URL",
    "PROXY_USERNAME_TEMPLATE",
    "PROXY_PASSWORD",
    "PROXY_DOMAIN_DELAY_SECONDS",
    "PROXY_BLOCK_BACKOFF_SECONDS",
    "PROXY_LIST_FILE",
    "WEBSHARE_PROXY_LIST_FILE",
)


@pytest.fixture(autouse=True)
def isolate_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must opt in to proxy env vars rather than inherit them from .env."""
    for name in _PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
