"""Tests for src/output.py — write_results."""

from __future__ import annotations

import json
import logging

from crawl_tool.engine.models import PageResult
from crawl_tool.engine.output import write_results


def _page(success: bool = True, title: str = "Test") -> PageResult:
    return PageResult(
        url="https://cafef.vn/article.chn",
        final_url="https://cafef.vn/article.chn",
        status_code=200 if success else 500,
        title=title,
        markdown="Nội dung bài viết kinh tế",
        html="<html>raw</html>",
        raw_markdown="raw markdown",
        success=success,
        error=None if success else "fetch failed",
    )


def test_write_results_json_produces_valid_json(tmp_path):
    path = str(tmp_path / "out.json")
    write_results([_page()], path, fmt="json")
    data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert "meta" in data
    assert "pages" in data


def test_write_results_jsonl_produces_one_line_per_page(tmp_path):
    path = str(tmp_path / "out.jsonl")
    write_results([_page(), _page()], path, fmt="jsonl")
    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # each line must be valid JSON


def test_write_results_json_injects_run_meta(tmp_path):
    path = str(tmp_path / "out.json")
    write_results([_page()], path, fmt="json", run_meta={"goal": "test goal"})
    meta = json.loads((tmp_path / "out.json").read_text())["meta"]
    assert meta["goal"] == "test goal"


def test_write_results_json_excludes_html_and_raw_markdown(tmp_path):
    path = str(tmp_path / "out.json")
    write_results([_page()], path, fmt="json")
    pages = json.loads((tmp_path / "out.json").read_text())["pages"]
    assert "html" not in pages[0]
    assert "raw_markdown" not in pages[0]


def test_write_results_json_preserves_vietnamese_text(tmp_path):
    path = str(tmp_path / "out.json")
    write_results([_page()], path, fmt="json")
    raw = (tmp_path / "out.json").read_text(encoding="utf-8")
    assert "Nội dung bài viết kinh tế" in raw


def test_write_results_json_empty_pages(tmp_path):
    path = str(tmp_path / "out.json")
    write_results([], path, fmt="json")
    data = json.loads((tmp_path / "out.json").read_text())
    assert data["meta"]["total_pages"] == 0
    assert data["pages"] == []


def test_write_results_logs_output_summary(tmp_path, caplog):
    path = str(tmp_path / "out.json")
    with caplog.at_level(logging.INFO, logger="crawl_tool.engine.output"):
        write_results([_page(), _page(success=False)], path)
    payload = next(
        json.loads(record.message)
        for record in caplog.records
        if json.loads(record.message).get("event") == "output summary"
    )
    assert payload["path"] == path
    assert payload["format"] == "json"
    assert payload["total"] == 2
    assert payload["successful"] == 1
    assert payload["failed"] == 1
