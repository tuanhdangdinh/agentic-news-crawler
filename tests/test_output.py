"""Tests for src/output.py — write_results, write_json, write_jsonl."""

from __future__ import annotations

import json
import logging

from src.crawler import PageResult
from src.output import write_json, write_jsonl, write_results


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


# ---------------------------------------------------------------------------
# write_results
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# write_json
# ---------------------------------------------------------------------------

def test_write_json_meta_fields_present(tmp_path):
    path = str(tmp_path / "out.json")
    write_json([_page(), _page(success=False)], path)
    meta = json.loads((tmp_path / "out.json").read_text())["meta"]
    assert "generated_at" in meta
    assert meta["total_pages"] == 2
    assert meta["successful"] == 1
    assert meta["failed"] == 1


def test_write_json_successful_plus_failed_equals_total(tmp_path):
    path = str(tmp_path / "out.json")
    pages = [_page(success=True), _page(success=True), _page(success=False)]
    write_json(pages, path)
    meta = json.loads((tmp_path / "out.json").read_text())["meta"]
    assert meta["successful"] + meta["failed"] == meta["total_pages"]


def test_write_json_run_meta_merged(tmp_path):
    path = str(tmp_path / "out.json")
    write_json([_page()], path, run_meta={"seed_url": "https://cafef.vn", "finish_reason": "done"})
    meta = json.loads((tmp_path / "out.json").read_text())["meta"]
    assert meta["seed_url"] == "https://cafef.vn"
    assert meta["finish_reason"] == "done"


# ---------------------------------------------------------------------------
# write_jsonl
# ---------------------------------------------------------------------------

def test_write_jsonl_line_count_matches_pages(tmp_path):
    path = str(tmp_path / "out.jsonl")
    pages = [_page(), _page(), _page()]
    write_jsonl(pages, path)
    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(pages)


def test_write_jsonl_each_line_is_valid_json(tmp_path):
    path = str(tmp_path / "out.jsonl")
    write_jsonl([_page(), _page(success=False)], path)
    for line in (tmp_path / "out.jsonl").read_text(encoding="utf-8").strip().splitlines():
        record = json.loads(line)
        assert "url" in record


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def test_write_results_logs_nothing_on_success(tmp_path, caplog):
    path = str(tmp_path / "out.json")
    with caplog.at_level(logging.WARNING, logger="src.output"):
        write_results([_page()], path)
    assert caplog.records == []
