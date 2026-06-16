"""Tests for src/output.py — write_json."""

from __future__ import annotations

import json

from crawl_tool.engine.models import PageResult
from crawl_tool.engine.output import write_json


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
