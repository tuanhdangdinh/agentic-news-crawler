import pytest

from src.logging_config import configure_logging


@pytest.fixture(autouse=True, scope="session")
def setup_logging():
    configure_logging(verbose=True)
