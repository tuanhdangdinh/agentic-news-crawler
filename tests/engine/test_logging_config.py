"""Tests for structured logging configuration."""

from __future__ import annotations

import json

import structlog

from crawl_tool.engine.logging_config import configure_logging


def test_configure_logging_outputs_stable_json_field_order(capsys):
    configure_logging()

    structlog.get_logger("tests.logging").info("sample event", zed=1, alpha=2)

    captured = capsys.readouterr()
    log_line = captured.err.strip()
    payload = json.loads(log_line)

    assert list(payload) == ["timestamp", "level", "logger", "event", "alpha", "zed"]
    assert payload["level"] == "info"
    assert payload["logger"] == "tests.logging"
    assert payload["event"] == "sample event"
    assert payload["alpha"] == 2
    assert payload["zed"] == 1
