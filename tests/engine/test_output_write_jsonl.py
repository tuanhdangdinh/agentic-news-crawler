"""Tests for src/output.py — write_jsonl."""

from __future__ import annotations

import json

from crawl_tool.engine.models import PageResult
from crawl_tool.engine.output import write_jsonl


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
