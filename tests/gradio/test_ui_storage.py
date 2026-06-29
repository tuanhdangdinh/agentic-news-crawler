"""Tests for storage page helpers."""
from __future__ import annotations


def test_format_size_bytes():
    from crawl_tool.gradio.ui_storage import _format_size

    assert _format_size(512) == "512 B"
    assert _format_size(1024) == "1.0 KB"
    assert _format_size(1536) == "1.5 KB"
    assert _format_size(1_048_576) == "1.0 MB"
    assert _format_size(1_073_741_824) == "1.0 GB"


def test_build_stats_html_shows_file_count():
    from crawl_tool.gradio.ui_storage import _build_stats_html

    overview = {
        "total_files": 5,
        "total_size_bytes": 10240,
        "last_modified": "2026-06-29T10:00:00+00:00",
        "objects": [],
    }
    html = _build_stats_html(overview)
    assert "5" in html
    assert "KB" in html
    assert "2026-06-29" in html


def test_build_stats_html_empty_bucket():
    from crawl_tool.gradio.ui_storage import _build_stats_html

    overview = {"total_files": 0, "total_size_bytes": 0, "last_modified": None, "objects": []}
    html = _build_stats_html(overview)
    assert "0" in html
